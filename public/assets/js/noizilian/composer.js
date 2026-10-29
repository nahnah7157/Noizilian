// 학종이 작성기: 감각 막대 4개 → 색·질감 → 타일.
// chat.html의 #signal-composer 안에 그린다. chatbot.js는 window.noizilian.getSignal()로 현재 신호를 읽는다.

import { AXES, AXIS_WORDS } from "./senseModel.js";
import { colorFor, describe, scoresOf, textureFor } from "./library.js";
import { renderTile } from "./renderTile.js";

const root = document.getElementById("signal-composer");
if (root) {
  const canvas = root.querySelector("canvas");
  const sliders = {};
  let seed = 42;
  let current = null;
  let frame = 0;

  // 막대 하나: 손잡이 = 원하는 점수, 검은 점 = 실제로 만들어진 타일의 점수
  for (const axis of AXES) {
    const [left, right] = AXIS_WORDS[axis];
    const row = root.querySelector(`[data-axis="${axis}"]`);
    row.innerHTML = `
      <span class="sense-word">${left}</span>
      <div class="sense-bar">
        <input id="sense-${axis}" type="range" min="-100" max="100" value="0" aria-label="${left}–${right}">
        <i class="sense-actual" aria-hidden="true"></i>
      </div>
      <span class="sense-word right">${right}</span>`;
    const input = row.querySelector("input");
    input.addEventListener("input", schedule);
    sliders[axis] = { input, dot: row.querySelector(".sense-actual") };
  }

  root.querySelector("[data-reseed]")?.addEventListener("click", () => {
    seed = Math.floor(Math.random() * 100000);
    schedule();
  });

  function value(axis) {
    return Number(sliders[axis].input.value) / 100;
  }

  function schedule() {
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(update);
  }

  function update() {
    const texture = textureFor(value("hs")); // 질감: 단단함–부드러움 막대만으로
    const color = colorFor({ wc: value("wc"), mf: value("mf"), hl: value("hl") }, texture); // 색: 나머지 3축
    renderTile(canvas, color, texture, seed);
    const scores = scoresOf(color, texture);
    AXES.forEach((a) => (sliders[a].dot.style.left = `${((scores[a] + 1) / 2) * 100}%`));
    current = { color, texture, seed, scores, description: describe(scores) };
  }

  window.noizilian = {
    /** 지금 학종이의 색·질감·점수. 서버로 보낼 때 쓴다. */
    getSignal: () => current && structuredClone(current),
    /** 채팅 말풍선에 붙일 타일 이미지 */
    tileImage: () => canvas.toDataURL("image/png"),
  };

  update();
}
