// ════════════════════════════════════════════════════════════
// Noizilian 학종이 작성기 + 채팅
// 1. 색 변환  2. 감각 공식  3. 색·질감 목록과 찾기  4. 타일 그리기  5. 학종이 작성기  6. 채팅
// ════════════════════════════════════════════════════════════

// ── 1. 색 변환 ──────────────────────────────────────────────
// CIELAB(LCh) → sRGB 변환. 논문은 sRGB로 보정한 모니터에서 L*, C*, h 값을 사용했다.

function lchToLinearRgb({ L, C, h }) {
  const r = (h * Math.PI) / 180;
  const a = C * Math.cos(r);
  const b = C * Math.sin(r);
  const fy = (L + 16) / 116;
  const fx = fy + a / 500;
  const fz = fy - b / 200;
  const finv = (t) => (t ** 3 > 0.008856 ? t ** 3 : (t - 16 / 116) / 7.787);
  const X = 0.95047 * finv(fx);
  const Y = finv(fy);
  const Z = 1.08883 * finv(fz);
  return [
    3.2406 * X - 1.5372 * Y - 0.4986 * Z,
    -0.9689 * X + 1.8758 * Y + 0.0415 * Z,
    0.0557 * X - 0.204 * Y + 1.057 * Z,
  ];
}

/** 모니터(sRGB)에서 표시할 수 있는 색인지 */
function inGamut(c) {
  return lchToLinearRgb(c).every((v) => v >= -0.001 && v <= 1.001);
}

/** 0~255 RGB 배열 */
function lchToRgb(c) {
  return lchToLinearRgb(c).map((v) => {
    const g = v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(Math.max(v, 0), 1 / 2.4) - 0.055;
    return Math.round(Math.min(1, Math.max(0, g)) * 255);
  });
}

// ── 2. 감각 공식 ────────────────────────────────────────────
// Lucassen, Gevers, Gijsenij (2011) "Texture Affects Color Emotion", Table III
// 색 질감(Color Texture) 공식. 결과는 대략 -4~+4, 음수 = 왼쪽 단어.
// 주의: PDF 표에서 마이너스 기호가 "2"로 깨져 보인다(예: "20.80" = -0.80).
// 서버의 services/chatbot_service.py(1. 학종이 신호 해석)와 같은 공식이다. 한쪽을 고치면 다른 쪽도 고친다.

const AXES = ["wc", "mf", "hs", "hl"];
const AXIS_WORDS = {
  wc: ["따뜻함", "차가움"],
  mf: ["남성적", "여성적"],
  hs: ["단단함", "부드러움"],
  hl: ["무거움", "가벼움"],
};

const cosd = (deg) => Math.cos((deg * Math.PI) / 180);

/** color = {L, C, h}, texture = {oct, freq, pers, lac} */
function rawScores({ L, C, h }, { oct, freq, pers, lac }) {
  return {
    wc: -0.8 + 0.015 * L - 0.2 * C ** 0.65 * cosd(h - 40) + 0.056 * oct,
    mf: 0.84 * L ** 0.25 + 0.022 * C - 0.017 * h + 0.00000014 * h ** 3 - 0.57 * oct ** 0.5 - 0.7 * freq ** 0.5,
    // 단단함–부드러움: 색 변수가 없다. 질감만으로 결정된다.
    hs: 586.33 - 178.78 * oct ** 0.01 - 84.2 * freq ** 0.01 - 106.83 * pers ** 0.02 - 213.89 * lac ** 0.01,
    hl: 0.33 * L ** 0.6 + 0.02 * C ** 0.8 - 2.57 * oct ** 0.1 - 1.41 * freq ** 0.1 + 0.015 * lac ** 3,
  };
}

// ── 3. 색·질감 목록과 "원하는 점수 → 가장 가까운 색/질감" 찾기 ──
// 색·질감 목록과 "원하는 점수 → 가장 가까운 색/질감" 찾기.
// 공식을 거꾸로 풀지 않고, 미리 만든 목록에서 가장 가까운 항목을 고른다.


// 색 목록: 논문과 같은 밝기·색상·채도 격자를 더 촘촘하게 (화면에 표시 가능한 색만)
const COLORS = [];
for (let L = 10; L <= 90; L += 5)
  for (let h = 0; h < 360; h += 10)
    for (let C = 0; C <= 110; C += 5) {
      if (C === 0 && h > 0) continue; // 무채색은 한 번만
      const c = { L, C, h };
      if (inGamut(c)) COLORS.push(c);
    }

// 질감 목록: 논문 그림 2 기준값(옥타브 6, 주파수 0.5, 지속성 0.6, 공극성 2.5) 주변
const TEXTURES = [];
for (let oct = 1; oct <= 12; oct++)
  for (const freq of [0.4, 0.5, 0.6, 0.75, 0.9])
    for (const pers of [0.4, 0.5, 0.6, 0.7, 0.8])
      for (const lac of [1.8, 2.2, 2.5, 2.9, 3.2]) TEXTURES.push({ oct, freq, pers, lac });

// 정규화 범위: 공식이 질감 변수마다 한 방향으로만 변하므로, 질감 범위 양 끝 16개 조합 × 모든 색에서 최솟값·최댓값을 구한다.
const RANGE = {};
{
  const corners = [];
  for (const oct of [1, 12]) for (const freq of [0.4, 0.9]) for (const pers of [0.4, 0.8]) for (const lac of [1.8, 3.2])
    corners.push({ oct, freq, pers, lac });
  AXES.forEach((a) => (RANGE[a] = [Infinity, -Infinity]));
  for (const c of COLORS)
    for (const t of corners) {
      const s = rawScores(c, t);
      AXES.forEach((a) => {
        RANGE[a][0] = Math.min(RANGE[a][0], s[a]);
        RANGE[a][1] = Math.max(RANGE[a][1], s[a]);
      });
    }
}

/** 논문 점수를 -1(왼쪽 단어) ~ +1(오른쪽 단어)로 맞춘 값 */
function scoresOf(c, t) {
  const raw = rawScores(c, t);
  const out = {};
  AXES.forEach((a) => {
    const [lo, hi] = RANGE[a];
    out[a] = Math.max(-1, Math.min(1, ((raw[a] - lo) / (hi - lo)) * 2 - 1));
  });
  return out;
}

/** 단단함–부드러움 막대 → 질감만 고른다 (논문: 이 축은 질감이 전부 결정) */
function textureFor(hsTarget) {
  const anyColor = COLORS[0]; // hs 공식에는 색이 없으므로 어떤 색이든 결과가 같다
  let best = TEXTURES[0];
  let bestD = Infinity;
  for (const t of TEXTURES) {
    const d = Math.abs(scoresOf(anyColor, t).hs - hsTarget);
    if (d < bestD) [best, bestD] = [t, d];
  }
  return best;
}

/** 온도·인상·무게 막대 → 지금 질감은 그대로 두고 색만 고른다 */
function colorFor(target, tex) {
  let best = COLORS[0];
  let bestD = Infinity;
  for (const c of COLORS) {
    const s = scoresOf(c, tex);
    const d = (s.wc - target.wc) ** 2 + (s.mf - target.mf) ** 2 + (s.hl - target.hl) ** 2;
    if (d < bestD) [best, bestD] = [c, d];
  }
  return best;
}

/** 점수를 한국어 설명으로 ("차갑고 단단한 신호") */
function describe(s) {
  const forms = {
    wc: [["따뜻하고", "따뜻한"], ["차갑고", "차가운"]],
    hs: [["단단하고", "단단한"], ["부드럽고", "부드러운"]],
    hl: [["무겁고", "무거운"], ["가볍고", "가벼운"]],
    mf: [["남성적이고", "남성적인"], ["여성적이고", "여성적인"]],
  };
  const words = ["wc", "hs", "hl", "mf"].filter((a) => Math.abs(s[a]) > 0.25).map((a) => forms[a][s[a] < 0 ? 0 : 1]);
  if (!words.length) return "뚜렷한 쪽이 없는 중립 신호";
  return words.map((p, i) => (i === words.length - 1 ? p[1] : p[0])).join(" ") + " 신호";
}

// ── 4. 타일 그리기 ──────────────────────────────────────────
// 논문 그림 3과 같은 방식: 흑백 펄린 노이즈 질감 × 단색 = 색 질감


function mulberry32(seed) {
  return () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function makePerlin(seed) {
  const rand = mulberry32(seed);
  const a = Array.from({ length: 256 }, (_, i) => i);
  for (let i = 255; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  const p = new Uint8Array(512);
  for (let i = 0; i < 512; i++) p[i] = a[i & 255];
  const grad = (h, x, y) => {
    switch (h & 7) {
      case 0: return x + y;
      case 1: return -x + y;
      case 2: return x - y;
      case 3: return -x - y;
      case 4: return x;
      case 5: return -x;
      case 6: return y;
      default: return -y;
    }
  };
  const fade = (t) => t * t * t * (t * (t * 6 - 15) + 10);
  return (x, y) => {
    const X = Math.floor(x) & 255;
    const Y = Math.floor(y) & 255;
    x -= Math.floor(x);
    y -= Math.floor(y);
    const u = fade(x);
    const v = fade(y);
    const aa = p[p[X] + Y], ab = p[p[X] + Y + 1], ba = p[p[X + 1] + Y], bb = p[p[X + 1] + Y + 1];
    const l1 = grad(aa, x, y) + u * (grad(ba, x - 1, y) - grad(aa, x, y));
    const l2 = grad(ab, x, y - 1) + u * (grad(bb, x - 1, y - 1) - grad(ab, x, y - 1));
    return l1 + v * (l2 - l1);
  };
}

/** 같은 색·질감·seed면 항상 같은 이미지가 나온다 */
function renderTile(canvas, color, tex, seed) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width;
  const H = canvas.height;
  const img = ctx.createImageData(W, H);
  const noise = makePerlin(seed);
  const rgb = lchToRgb(color);
  const oct = Math.max(1, Math.round(tex.oct));

  for (let y = 0; y < H; y++)
    for (let x = 0; x < W; x++) {
      let sum = 0, amp = 1, fr = tex.freq * 7, total = 0;
      for (let o = 0; o < oct; o++) {
        sum += amp * noise((x / W) * fr + o * 17.3, (y / H) * fr + o * 9.1);
        total += amp;
        amp *= tex.pers; // 지속성: 옥타브마다 진폭 감소
        fr *= tex.lac; // 공극성: 옥타브마다 주파수 증가
      }
      const v = Math.max(0, Math.min(1, 0.5 + (0.75 * sum) / total));
      const k = 0.22 + 1.15 * v;
      const i = (y * W + x) * 4;
      img.data[i] = Math.min(255, rgb[0] * k);
      img.data[i + 1] = Math.min(255, rgb[1] * k);
      img.data[i + 2] = Math.min(255, rgb[2] * k);
      img.data[i + 3] = 255;
    }
  ctx.putImageData(img, 0, 0);
}

// ── 5. 학종이 작성기 ────────────────────────────────────────
(() => {
// 학종이 작성기: 감각 막대 4개 → 색·질감 → 타일.
// chat.html의 #signal-composer 안에 그린다. 아래 채팅 코드는 window.noizilian.getSignal()로 현재 신호를 읽는다.


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
    // 휠 위 = 오른쪽. passive: false여야 페이지 스크롤을 막을 수 있음
    input.addEventListener("wheel", (event) => {
      event.preventDefault();
      input.value = Number(input.value) + (event.deltaY < 0 ? 5 : -5);
      schedule();
    }, { passive: false });
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
})();

// ── 6. 채팅 및 요리 진행 ─────────────────────────────────────
const shell = document.querySelector(".chat-area");
const form = document.getElementById("chat-form");
const input = document.getElementById("user-message");
const log = document.getElementById("chat-log");
const sendButton = document.getElementById("send-btn");

const dishNameEl = document.getElementById("dish-name");
const stageStepsEl = document.getElementById("stage-steps");
const stageHintEl = document.getElementById("stage-hint");
const confidenceFillEl = document.getElementById("confidence-fill");
const resultOverlayEl = document.getElementById("result-overlay");
const resultImageEl = document.getElementById("result-image");
const resultLineEl = document.getElementById("result-line");
const restartBtn = document.getElementById("restart-btn");

let currentState = null;
let currentStageId = null;
let currentDishId = null;
const stageNames = {};
// 레코드에 새길 대화: 지구인 {who, stage, message, signal, scores} / 외계인 {who, stage, message, scores}
let history = [];

const STAGE_NAMES = ["재료 준비", "손질", "조리", "플레이팅"];

function addMessage(sender, text, image = null, imageClass = "", alienScores = null) {
  const item = document.createElement("div");
  item.className = `message ${sender}`;

  if (image) {
    const img = document.createElement("img");
    img.src = image;
    img.alt = imageClass ? "내가 보낸 학종이" : "외계인 표정/요리 이미지";
    if (imageClass) img.className = imageClass;
    item.append(img);
  }

  if (alienScores) {
    const canvas = document.createElement("canvas");
    canvas.width = 100;
    canvas.height = 100;
    canvas.style.display = "block";
    canvas.style.marginBottom = "8px";
    canvas.style.borderRadius = "6px";
    const texture = textureFor(alienScores.hs);
    const color = colorFor({ wc: alienScores.wc, mf: alienScores.mf, hl: alienScores.hl }, texture);
    renderTile(canvas, color, texture, 12345);
    item.append(canvas);
  }

  const body = document.createElement("p");
  body.textContent = text;
  item.append(body);

  log.append(item);
  log.scrollTop = log.scrollHeight;
  return item;
}

function updateGameState(data) {
  if (data.state) {
    currentState = data.state;
  }

  if (data.stage) {
    currentStageId = data.stage.id;
    stageNames[data.stage.id] = data.stage.name;
  }
  if (data.dish) currentDishId = data.dish.id;

  if (data.dish && dishNameEl) {
    dishNameEl.textContent = `목표 요리: ${data.dish.name}`;
  }

  if (data.stage && stageStepsEl) {
    const currentIndex = data.stage.index;
    stageStepsEl.innerHTML = STAGE_NAMES.map((name, idx) => {
      let cls = "stage-step";
      if (idx === currentIndex) cls += " active";
      else if (idx < currentIndex) cls += " done";
      return `<span class="${cls}">${idx + 1}. ${name}</span>`;
    }).join("");

    if (stageHintEl) {
      stageHintEl.textContent = data.stage.hint || "";
    }

    if (data.stage.advanced) {
      addMessage("bot notice", `✨ 다음 단계(${data.stage.name})로 넘어갔습니다!`);
    }
  }

  if (currentState && typeof currentState.confidence === "number" && confidenceFillEl) {
    const pct = Math.round(currentState.confidence * 100);
    confidenceFillEl.style.width = `${pct}%`;
  }

  if (currentState && currentState.done) {
    if (data.result && resultOverlayEl) {
      if (resultImageEl) resultImageEl.src = data.result.image;
      if (resultLineEl) resultLineEl.textContent = data.result.line;
      resultOverlayEl.hidden = false;
      showRecord();
    }
    input.disabled = true;
    sendButton.disabled = true;
  }
}

function addAlienToHistory(data) {
  if (data.alien?.scores && data.stage) {
    history.push({ who: "alien", stage: data.stage.id, message: data.alien.word || "", scores: data.alien.scores });
  }
}

async function startCooking() {
  log.innerHTML = "";
  history = [];
  if (resultOverlayEl) resultOverlayEl.hidden = true;
  input.disabled = false;
  sendButton.disabled = false;

  const pending = addMessage("bot pending", "요리를 준비하는 중…");

  try {
    const response = await fetch("/api/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error?.message || "요리를 시작하지 못했습니다.");
    }
    pending.remove();
    addMessage("bot", data.reply, data.image, "", data.alien?.scores);
    addAlienToHistory(data);
    updateGameState(data);
  } catch (error) {
    pending.remove();
    addMessage("bot error", error.message || "오류가 발생했습니다.");
    input.disabled = true;
    sendButton.disabled = true;
  }
}

restartBtn?.addEventListener("click", () => {
  startCooking();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const signal = window.noizilian?.getSignal() ?? null;
  const message = input.value.trim() || signal?.description || "";
  if (!message || sendButton.disabled) return;

  addMessage("user", message, signal ? window.noizilian.tileImage() : null, signal ? "signal-image" : "");
  const sentStage = currentStageId;
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
        signal: signal ? { color: signal.color, texture: signal.texture, seed: signal.seed } : undefined,
        state: currentState || undefined,
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
    if (signal && sentStage) {
      history.push({
        who: "user", stage: sentStage, message,
        signal: { color: signal.color, texture: signal.texture, seed: signal.seed }, scores: signal.scores,
      });
    }
    addMessage("bot", data.reply, data.image, "", data.alien?.scores);
    addAlienToHistory(data);
    updateGameState(data);
  } catch (error) {
    pending.remove();
    addMessage("bot error", error.message || "오류가 발생했습니다.");
  } finally {
    if (!currentState?.done) {
      sendButton.disabled = false;
      input.focus();
    }
  }
});

// ── 7. 골든 레코드 ──────────────────────────────────────────
// 주고받은 타일을 바깥에서 안쪽으로 도는 나선 홈에 순서대로 새긴다. 홈 위에 마우스를 올리면 해석이 뜬다.

const recordCanvas = document.getElementById("record-canvas");
const recordTip = document.getElementById("record-tip");
const recordCaption = document.getElementById("record-caption");
const PER_TURN = 12; // 한 바퀴에 새기는 타일 수
let interpretations = null;
let recordToken = 0;

function recordGeometry() {
  const S = recordCanvas.width;
  return { S, band: S * 0.035, pitch: S * 0.045, outer: S * 0.44, step: (2 * Math.PI) / PER_TURN };
}

function arcOf(i) {
  const { band, pitch, outer, step } = recordGeometry();
  const start = -Math.PI / 2 + i * step;
  return { r: outer - (i * pitch) / PER_TURN - band / 2, start, end: start + step - 0.06 };
}

function tilePattern(ctx, entry) {
  const tile = document.createElement("canvas");
  tile.width = tile.height = 48;
  if (entry.who === "user") {
    renderTile(tile, entry.signal.color, entry.signal.texture, entry.signal.seed);
  } else {
    const texture = textureFor(entry.scores.hs);
    renderTile(tile, colorFor(entry.scores, texture), texture, 12345); // 채팅 말풍선의 외계인 타일과 같은 seed
  }
  return ctx.createPattern(tile, "repeat");
}

function drawRecord(highlight = -1) {
  const ctx = recordCanvas.getContext("2d");
  const { S, band } = recordGeometry();
  ctx.clearRect(0, 0, S, S);
  history.forEach((entry, i) => {
    const { r, start, end } = arcOf(i);
    entry.pattern ??= tilePattern(ctx, entry);
    ctx.beginPath();
    ctx.arc(S / 2, S / 2, r, start, end);
    ctx.lineWidth = band + 3;
    ctx.strokeStyle = i === highlight ? "#fff" : "rgb(0 0 0 / 45%)";
    ctx.stroke();
    ctx.lineWidth = band;
    ctx.strokeStyle = entry.pattern;
    ctx.stroke();
  });
}

function hitRecord(event) {
  const rect = recordCanvas.getBoundingClientRect();
  const { S, band } = recordGeometry();
  const x = ((event.clientX - rect.left) * S) / rect.width - S / 2;
  const y = ((event.clientY - rect.top) * S) / rect.height - S / 2;
  const r = Math.hypot(x, y);
  const angle = Math.atan2(y, x);
  return history.findIndex((_, i) => {
    const arc = arcOf(i);
    const d = (((angle - arc.start) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    return d <= arc.end - arc.start && Math.abs(r - arc.r) <= band / 2 + 2;
  });
}

function showTip(event, i) {
  const entry = history[i];
  const title = document.createElement("strong");
  title.textContent = `${i + 1}. ${entry.who === "user" ? "지구인" : "외계인"} · ${stageNames[entry.stage] || entry.stage}`;
  const item = interpretations?.[i];
  const line = document.createElement("q");
  line.textContent = item?.line || "";
  line.hidden = !item?.line;
  const basis = document.createElement("small");
  basis.textContent = item?.basis ?? (interpretations === null ? "해석을 만드는 중…" : describe(entry.scores));
  basis.hidden = Boolean(item?.line); // 대사가 있으면 대화만 보여 준다
  recordTip.replaceChildren(title, line, basis);
  recordTip.hidden = false;

  const box = recordTip.parentElement.getBoundingClientRect();
  const px = event.clientX - box.left;
  const py = event.clientY - box.top;
  // 커서 반대쪽에 띄워 레코드 밖으로 넘치지 않게
  recordTip.style.left = `${px < box.width / 2 ? px + 14 : px - recordTip.offsetWidth - 14}px`;
  recordTip.style.top = `${py < box.height / 2 ? py + 14 : py - recordTip.offsetHeight - 14}px`;
}

recordCanvas?.addEventListener("mousemove", (event) => {
  const i = hitRecord(event);
  if (i < 0) {
    recordTip.hidden = true;
    recordCanvas.style.cursor = "";
  } else {
    showTip(event, i);
    recordCanvas.style.cursor = "help";
  }
  drawRecord(i);
});

recordCanvas?.addEventListener("mouseleave", () => {
  recordTip.hidden = true;
  drawRecord();
});

const RECORD_NOTES = {
  no_key: "OpenAI 키가 없어 공식 계산으로 해석했어요.",
  openai_failed: "OpenAI 응답이 실패해 공식 계산으로 해석했어요.",
};

function showRecord() {
  if (!recordCanvas) return;
  recordTip.hidden = true;
  drawRecord();
  if (history.length) loadInterpretations();
}

async function loadInterpretations() {
  const token = ++recordToken;
  interpretations = null;
  recordCaption.textContent = "해석을 만드는 중이에요. 대화가 길면 30초쯤 걸려요.";
  try {
    const response = await fetch("/api/interpret", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dish: currentDishId,
        entries: history.map(({ who, stage, message, signal, scores }) =>
          who === "user" ? { who, stage, message, signal } : { who, stage, message, scores }),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "해석을 받지 못했습니다.");
    if (token !== recordToken) return; // 그 사이 다시 시작함
    interpretations = data.interpretations;
    recordCaption.textContent = "홈 위에 마우스를 올리면 그 신호의 해석이 보여요.";
    const [source, reason] = data.source.split(":");
    if (RECORD_NOTES[source]) recordCaption.textContent += ` (${RECORD_NOTES[source]}${reason ? ` 오류: ${reason}` : ""})`;
    if (source === "openai_failed") recordCaption.append(retryButton());
  } catch (error) {
    if (token !== recordToken) return;
    interpretations = [];
    // "Failed to fetch" = 서버와 연결이 끊김(서버 종료·재시작 등)
    recordCaption.textContent = `서버에 연결하지 못해 신호 이름만 보여요. 서버가 켜져 있는지 확인해 주세요. (${error.message})`;
    recordCaption.append(retryButton());
  }
}

function retryButton() {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "reseed-button";
  button.textContent = "다시 시도";
  button.addEventListener("click", loadInterpretations);
  return button;
}

// 페이지 시작 시 요리 시작 API 호출
if (shell) {
  startCooking();
}

