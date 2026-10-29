const shell = document.querySelector(".chat-area");
const form = document.getElementById("chat-form");
const input = document.getElementById("user-message");
const log = document.getElementById("chat-log");
const sendButton = document.getElementById("send-btn");

function addMessage(sender, text, image = null, imageClass = "") {
  const item = document.createElement("div");
  item.className = `message ${sender}`;

  if (image) {
    const img = document.createElement("img");
    img.src = image;
    img.alt = imageClass ? "내가 보낸 학종이" : "챗봇이 보낸 이미지";
    if (imageClass) img.className = imageClass;
    item.append(img);
  }

  const body = document.createElement("p");
  body.textContent = text;
  item.append(body);

  log.append(item);
  log.scrollTop = log.scrollHeight;
  return item;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  // 학종이 작성기(noizilian/composer.js)가 있으면 현재 신호를 함께 보낸다.
  const signal = window.noizilian?.getSignal() ?? null;
  const message = input.value.trim() || signal?.description || "";
  if (!message || sendButton.disabled) return;

  addMessage("user", message, signal ? window.noizilian.tileImage() : null, signal ? "signal-image" : "");
  input.value = "";
  sendButton.disabled = true;
  const pending = addMessage("bot pending", "답변을 기다리는 중…");

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message,
        username: shell.dataset.username || "사용자",
        // 점수는 서버가 같은 논문 공식으로 다시 계산하므로 색·질감·seed만 보낸다.
        signal: signal ? { color: signal.color, texture: signal.texture, seed: signal.seed } : undefined,
      }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error?.message || "답변을 받지 못했습니다.");
    }
    if (typeof data.reply !== "string") {
      throw new Error("서버 응답 형식이 올바르지 않습니다.");
    }
    pending.remove();
    addMessage("bot", data.reply, data.image);
  } catch (error) {
    pending.remove();
    addMessage("bot error", error.message || "오류가 발생했습니다.");
  } finally {
    sendButton.disabled = false;
    input.focus();
  }
});
