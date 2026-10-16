// Этап 2 (по желанию): мгновенная реакция на кнопки.
// Cloudflare Worker принимает вебхук Telegram, сразу отвечает на нажатие
// и запускает GitHub-воркфлоу с этим нажатием (repository_dispatch).
// Переменные Worker: TG_TOKEN, TG_SECRET (любая строка), GH_TOKEN (fine-grained, Contents: read/write), GH_REPO ("user/3l-bot").
// Вебхук: https://api.telegram.org/bot<TOKEN>/setWebhook?url=<WORKER_URL>&secret_token=<TG_SECRET>
export default {
  async fetch(req, env) {
    if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.TG_SECRET) return new Response("no", { status: 403 });
    const update = await req.json();
    const q = update.callback_query;
    if (q) {
      await fetch(`https://api.telegram.org/bot${env.TG_TOKEN}/answerCallbackQuery`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ callback_query_id: q.id, text: q.data.startsWith("y:") ? "Принято, готовлю черновик" : "Мимо" }),
      });
    }
    await fetch(`https://api.github.com/repos/${env.GH_REPO}/dispatches`, {
      method: "POST",
      headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "3l-relay" },
      body: JSON.stringify({ event_type: "tg", client_payload: { update } }),
    });
    return new Response("ok");
  },
};
