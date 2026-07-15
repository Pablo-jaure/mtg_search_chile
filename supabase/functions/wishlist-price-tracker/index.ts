import { createClient } from "https://esm.sh/@supabase/supabase-js@2";

declare const EdgeRuntime: { waitUntil(promise: Promise<unknown>): void };

type TrackerCard = { id: string; card_key: string; card_name: string; attempts: number };
type Delivery = {
  id: string; recipient_email: string; card_name: string; target_price_clp: number;
  current_price_clp: number; store_name: string; product_name: string; product_url: string;
};

const env = (name: string): string => {
  const value = Deno.env.get(name)?.trim();
  if (!value) throw new Error(`Missing ${name}`);
  return value;
};

const secretKey = (): string => {
  const keys = JSON.parse(env("SUPABASE_SECRET_KEYS"));
  if (!keys.default) throw new Error("SUPABASE_SECRET_KEYS.default is missing");
  return keys.default;
};

const html = (value: string) => value.replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]!));

const clp = (value: number) => new Intl.NumberFormat("es-CL", {
  style: "currency", currency: "CLP", maximumFractionDigits: 0,
}).format(value);

async function signature(secret: string, timestamp: string, nonce: string, body: string) {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"],
  );
  const bytes = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(`${timestamp}.${nonce}.${body}`));
  return Array.from(new Uint8Array(bytes)).map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function checkRender(card: TrackerCard) {
  const body = JSON.stringify({ card_name: card.card_name });
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = crypto.randomUUID();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120_000);
  try {
    const response = await fetch(env("RENDER_TRACKER_URL"), {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-tracker-timestamp": timestamp,
        "x-tracker-nonce": nonce,
        "x-tracker-signature": await signature(env("PRICE_TRACKER_INTERNAL_SECRET"), timestamp, nonce, body),
      },
      body,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`Render ${response.status}: ${payload.error ?? "invalid response"}`);
    return payload as {
      price_clp: number | null; store_name: string | null; product_name: string | null;
      product_url: string | null; offers_count: number;
    };
  } finally {
    clearTimeout(timeout);
  }
}

async function sendDelivery(delivery: Delivery) {
  const wishlistUrl = new URL("/wishlist", env("APP_PUBLIC_URL")).toString();
  const response = await fetch("https://api.resend.com/emails", {
    method: "POST",
      headers: { "authorization": `Bearer ${env("RESEND_API_KEY")}`, "content-type": "application/json; charset=utf-8" },
    body: JSON.stringify({
      from: env("ALERT_FROM_EMAIL"),
      to: [delivery.recipient_email],
      subject: `${delivery.card_name} llegó a tu precio objetivo`,
      html: `<!doctype html><html lang="es"><head><meta charset="UTF-8"></head><body>
        <h2>¡Tu carta bajó de precio!</h2>
        <p><strong>${html(delivery.card_name)}</strong> está a ${clp(delivery.current_price_clp)},
        igual o bajo tu objetivo de ${clp(delivery.target_price_clp)}.</p>
        <p>Tienda: ${html(delivery.store_name)}<br>Producto: ${html(delivery.product_name)}</p>
        <p><a href="${html(delivery.product_url)}">Ver producto</a> · <a href="${html(wishlistUrl)}">Ver wishlist</a></p>
        <p>Esta alerta se envía una sola vez. Puedes reactivarla desde tu wishlist.</p>
        </body></html>`,
    }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(`Resend ${response.status}: ${payload.message ?? "invalid response"}`);
  return payload.id as string;
}

Deno.serve(async (request) => {
  try {
    const expected = `Bearer ${env("PRICE_TRACKER_CRON_SECRET")}`;
    if (request.method !== "POST" || request.headers.get("authorization") !== expected) {
      return Response.json({ error: "Unauthorized" }, { status: 401 });
    }

    const supabase = createClient(env("SUPABASE_URL"), secretKey(), {
      auth: { persistSession: false, autoRefreshToken: false },
    });
    const requested = await request.json().catch(() => ({}));
    const { data: runId, error: runError } = await supabase.rpc("start_or_resume_price_tracker_run");
    if (runError) throw runError;
    const { data: cards, error: claimError } = await supabase.rpc("claim_price_tracker_card", { p_run_id: runId });
    if (claimError) throw claimError;
    const card = (cards?.[0] ?? null) as TrackerCard | null;

    if (card) {
      try {
        const quote = await checkRender(card);
        const { error: recordError } = await supabase.rpc("record_price_tracker_result", {
          p_run_card_id: card.id, p_price_clp: quote.price_clp, p_store_name: quote.store_name,
          p_product_name: quote.product_name, p_product_url: quote.product_url, p_offers_count: quote.offers_count,
        });
        if (recordError) throw recordError;
        const { error } = await supabase.rpc("finish_price_tracker_card", { p_run_card_id: card.id, p_error: null });
        if (error) throw error;
      } catch (error) {
        await supabase.rpc("finish_price_tracker_card", {
          p_run_card_id: card.id, p_error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    const { data: deliveries, error: deliveryError } = await supabase.rpc("claim_price_alert_delivery");
    if (deliveryError) throw deliveryError;
    const delivery = (deliveries?.[0] ?? null) as Delivery | null;
    if (delivery) {
      try {
        const messageId = await sendDelivery(delivery);
        await supabase.rpc("finish_price_alert_delivery", {
          p_delivery_id: delivery.id, p_provider_message_id: messageId, p_error: null,
        });
      } catch (error) {
        await supabase.rpc("finish_price_alert_delivery", {
          p_delivery_id: delivery.id, p_provider_message_id: null,
          p_error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    // One card per invocation. Chain only when work was claimed; the next invocation safely claims the next row.
    if ((card || delivery) && !requested.no_chain) {
      EdgeRuntime.waitUntil(fetch(request.url, {
        method: "POST", headers: { authorization: expected, "content-type": "application/json" },
        body: JSON.stringify({ chained: true }),
      }).catch((error) => console.error("Could not chain tracker", error)));
    }
    return Response.json({ run_id: runId, processed_card: card?.card_name ?? null, processed_delivery: delivery?.id ?? null });
  } catch (error) {
    console.error(error);
    return Response.json({ error: error instanceof Error ? error.message : String(error) }, { status: 500 });
  }
});
