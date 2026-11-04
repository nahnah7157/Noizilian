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

/** HSV(h:0~360, s:0~1, v:0~1) → sRGB 0~255. 오른쪽 색 선택기가 쓰는 색 모델 */
function hsvToRgb(h, s, v) {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  const [r, g, b] =
    h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x] :
    h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return [(r + m) * 255, (g + m) * 255, (b + m) * 255];
}

/** sRGB 0~255 → CIELAB {L, C, h}. lchToRgb의 역변환(점수 계산은 논문의 L·C·h로) */
function rgbToLch(r, g, b) {
  const lin = (u) => { u /= 255; return u <= 0.04045 ? u / 12.92 : ((u + 0.055) / 1.055) ** 2.4; };
  const R = lin(r), G = lin(g), B = lin(b);
  const X = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047;
  const Y = 0.2126 * R + 0.7152 * G + 0.0722 * B;
  const Z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883;
  const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const fx = f(X), fy = f(Y), fz = f(Z);
  const a = 500 * (fx - fy), bb = 200 * (fy - fz);
  let h = (Math.atan2(bb, a) * 180) / Math.PI;
  if (h < 0) h += 360;
  return { L: 116 * fy - 16, C: Math.hypot(a, bb), h };
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
// 색상 선택기(2D + 1D) + 질감 슬라이더(크기·밀도)로 타일을 만든다.
// 색상 선택: X=채도(C*), Y=밝기(L*), 슬라이더=색상각(h). 서버는 이 L/C/h값을 받는다.
// 질감: freq(크기)와 밀도(0~1)를 슬라이더로 선택. 밀도는 oct/pers/lac를 선형 변환한다 [앱 설정].

let seed = 42;
let current = null;
let currentHue = 0, currentSat = 0.7, currentVal = 0.85; // 오른쪽 선택기 상태(HSV)
let currentDensity = 0.5;
let currentFreq = 0.65;

const tileCanvas = document.getElementById("preview-tile");
const colorCanvas = document.getElementById("color-canvas");
const hueSlider = document.getElementById("hue-slider");

if (tileCanvas && colorCanvas && hueSlider) {
  // 색 네모 클릭·드래그: 가로=채도(S), 세로=명도(V)
  function pickColor(e) {
    const rect = colorCanvas.getBoundingClientRect();
    currentSat = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    currentVal = 1 - Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    update();
    renderColorCanvas();
  }
  let dragging = false;
  colorCanvas.addEventListener("mousedown", (e) => { dragging = true; pickColor(e); });
  colorCanvas.addEventListener("mousemove", (e) => { if (dragging) pickColor(e); });
  window.addEventListener("mouseup", () => { dragging = false; });

  // 무지개 색상(hue) 막대
  hueSlider.addEventListener("input", () => {
    currentHue = Number(hueSlider.value);
    renderColorCanvas();
    update();
  });

  // 크기·밀도 슬라이더
  for (const axis of ["freq", "density"]) {
    const row = document.querySelector(`[data-axis="${axis}"]`);
    if (row) {
      const [min, max] = axis === "freq" ? [0.9, 0.4] : [0, 1];
      const label = axis === "freq" ? "크기" : "밀도";
      row.innerHTML = `
        <span class="sense-icon ${axis}-min" aria-hidden="true"></span>
        <div class="sense-bar">
          <input id="sense-${axis}" type="range" min="${Math.min(min, max) * 100}" max="${Math.max(min, max) * 100}" value="${axis === "freq" ? 65 : 50}" aria-label="${label}">
        </div>
        <span class="sense-icon ${axis}-max" aria-hidden="true"></span>`;
      const input = row.querySelector("input");
      input.addEventListener("input", () => {
        if (axis === "density") currentDensity = Number(input.value) / 100;
        else currentFreq = (130 - Number(input.value)) / 100; // 왼쪽=작은(0.9)·오른쪽=큰(0.4)
        update();
      });
    }
  }

  // 취소한 타일 값(색·크기·밀도)으로 선택기를 돌려놓는다 (section 6 되돌리기에서 호출)
  function restore(sig) {
    if (!sig) return;
    currentHue = sig.hsv.h;
    currentSat = sig.hsv.s;
    currentVal = sig.hsv.v;
    currentDensity = sig.density;
    currentFreq = sig.texture.freq;
    hueSlider.value = currentHue;
    document.getElementById("sense-density").value = currentDensity * 100;
    document.getElementById("sense-freq").value = 130 - currentFreq * 100;
    renderColorCanvas();
    update();
  }

  // 색 네모 배경: 현재 hue의 채도(가로)×명도(세로) 그래디언트
  function renderColorCanvas() {
    const ctx = colorCanvas.getContext("2d");
    const W = colorCanvas.width;
    const H = colorCanvas.height;
    const imgData = ctx.createImageData(W, H);
    const d = imgData.data;
    for (let y = 0; y < H; y++)
      for (let x = 0; x < W; x++) {
        const [r, g, b] = hsvToRgb(currentHue, x / (W - 1), 1 - y / (H - 1));
        const i = (y * W + x) * 4;
        d[i] = r; d[i + 1] = g; d[i + 2] = b; d[i + 3] = 255;
      }
    ctx.putImageData(imgData, 0, 0);

    // 선택한 점 표시 (밝은 바탕엔 어둡게, 어두운 바탕엔 밝게). k = 캔버스 픽셀 / CSS 픽셀 (해상도가 바뀌어도 같은 크기)
    const k = W / (colorCanvas.clientWidth || W);
    const selectX = currentSat * W;
    const selectY = (1 - currentVal) * H;
    ctx.strokeStyle = currentVal > 0.5 ? "#333" : "#fff";
    ctx.lineWidth = 2 * k;
    ctx.beginPath();
    ctx.arc(selectX, selectY, 7 * k, 0, 2 * Math.PI);
    ctx.stroke();
  }

  function update() {
    const texture = densityToTexture(currentDensity);
    const [r, g, b] = hsvToRgb(currentHue, currentSat, currentVal);
    const color = rgbToLch(r, g, b); // 화면은 HSV, 점수는 논문의 L·C·h로
    renderTile(tileCanvas, color, texture, seed);
    const scores = scoresOf(color, texture);
    const hsv = { h: currentHue, s: currentSat, v: currentVal };
    current = { color, texture, seed, scores, density: currentDensity, hsv, description: describe(scores) };
  }

  window.noizilian = {
    getSignal: () => current && structuredClone(current),
    tileImage: () => tileCanvas.toDataURL("image/png"),
    redraw: () => { renderColorCanvas(); update(); }, // 캔버스 해상도를 바꾼 뒤 다시 그리기 (8번)
    restore,
  };

  renderColorCanvas();
  update();
}

// 밀도(0~1)를 질감 파라미터(oct/pers/lac)로 변환 [앱 설정]
function densityToTexture(density) {
  return {
    oct: 1 + density * 11,
    freq: currentFreq, // 크기 막대 [앱 설정]
    pers: 0.4 + density * 0.4,
    lac: 1.8 + density * 1.4,
  };
}
})();

// ── 6. 채팅 및 요리 진행 ─────────────────────────────────────
const shell = document.querySelector(".chat-area");
const sendButton = document.getElementById("send-btn");
const alienExpr = document.getElementById("alien-expression");
const resultOverlayEl = document.getElementById("result-overlay");
const resultImageEl = document.getElementById("result-image");
const restartBtn = document.getElementById("restart-btn");
const signalCenter = document.getElementById("signal-center");
const thinkEl = document.getElementById("alien-think");
const thinkTile = thinkEl?.querySelector(".think-tile");
const thinkDots = thinkEl?.querySelector(".think-dots");
const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

let currentState = null;
let currentStageId = null;
let currentStageIndex = 0;
let currentDishId = null;
let resultSuccess = true;
const stageNames = {};
// 레코드에 새길 대화: 지구인 {who, stage, message, signal, scores} / 외계인 {who, stage, message, scores}
let history = [];

const undoBtn = document.getElementById("undo-btn");
let undoStack = []; // 이번 단계에서 보낸 타일마다의 스냅샷 (되돌리기 = 보낸 타일 취소)
let awaiting = false; // 서버 응답 대기 중

const STAGE_IDS = ["ingredient", "prep", "cook", "plating"];

// 윗줄 외계인 4칸 / 아랫줄 나 4칸 = 4단계. 단계가 "끝났을 때만" 그 칸을 채운다(진행 중엔 빈칸).
function stageFinished(i) {
  return !!(currentState?.done || i < currentStageIndex);
}
function renderTileRecord() {
  const record = document.getElementById("tile-record");
  if (!record) return;
  record.innerHTML = "";
  for (const who of ["alien", "user"]) {
    const icon = document.createElement("img");
    icon.className = `record-row-icon ${who}`;
    // 나 = 이름 정하기 화면에서 고른 플레이어 (app.py가 male/female만 넘김)
    icon.src = who === "alien" ? "/assets/images/alien/alien_default.png"
      : `/assets/images/alien/player_${shell?.dataset.player || "male"}.png`;
    record.append(icon);
    STAGE_IDS.forEach((stageId, i) => {
      const cell = document.createElement("canvas");
      cell.width = cell.height = 120; // style.css #tile-record 칸 크기와 같게 (흐려지지 않게)
      cell.className = "record-cell";
      const entry = stageFinished(i) ? history.findLast(e => e.who === who && e.stage === stageId) : null;
      if (who === "alien" && entry) {
        const texture = textureFor(entry.scores.hs);
        renderTile(cell, colorFor(entry.scores, texture), texture, 12345);
      } else if (entry && entry.signal?.color) {
        renderTile(cell, entry.signal.color, entry.signal.texture, 54321);
      }
      record.append(cell);
    });
  }
}

// 가운데 외계인 이미지만 표정으로 교체 (게임 화면엔 글자 없음)
function showAlien(data) {
  if (data.image) alienExpr.src = data.image;
}

// 진행 중 외계인 머리 위 말풍선: 내가 방금 보낸 타일(없으면 "…")을 띄우고 깜박인다(속도 = 확신)
function updateThink() {
  if (!thinkEl) return;
  const show = !!(currentState && !currentState.done);
  thinkEl.hidden = !show;
  if (!show) return;
  signalCenter?.style.setProperty("--think", Math.max(0, Math.min(1, currentState.confidence || 0)).toFixed(3));
  const mine = history.findLast(e => e.who === "user" && e.stage === currentStageId);
  if (mine?.signal?.color && thinkTile) {
    renderTile(thinkTile, mine.signal.color, mine.signal.texture, 54321);
    thinkTile.hidden = false;
    if (thinkDots) thinkDots.hidden = true;
  } else {
    if (thinkTile) thinkTile.hidden = true;
    if (thinkDots) thinkDots.hidden = false;
  }
}
function hideThink() {
  if (thinkEl) thinkEl.hidden = true;
}

// 되돌릴 게 없거나 응답 대기 중이거나 요리가 끝났으면 비활성
function refreshUndo() {
  if (undoBtn) undoBtn.disabled = !undoStack.length || awaiting || !!currentState?.done;
}

// 한 타일을 (startX,startY)에서 칸으로 날려 보낸다. draw(canvas)로 타일을 그린다. 끝나면 resolve
function flyTile(draw, startX, startY, cell) {
  return new Promise((resolve) => {
    const fly = document.createElement("canvas");
    fly.width = fly.height = 80;
    draw(fly);
    fly.className = "fly-tile";
    const t0 = cell.getBoundingClientRect(); // 칸 위치 미리 잡기(그 사이 다시 그려도 안전)
    fly.style.left = `${startX - 40}px`;
    fly.style.top = `${startY - 40}px`;
    document.body.append(fly);
    let settled = false;
    const finish = () => { if (settled) return; settled = true; fly.remove(); resolve(); };
    fly.addEventListener("transitionend", finish, { once: true });
    setTimeout(() => {
      const dx = (t0.left + t0.width / 2) - startX;
      const dy = (t0.top + t0.height / 2) - startY;
      fly.style.transform = `translate(${dx}px, ${dy}px) scale(${t0.width / 80})`;
      setTimeout(finish, 900); // transitionend가 안 오면 안전장치
    }, 1200);
  });
}

// 단계 끝: 내 타일(말풍선)→아랫줄 칸, 외계인 타일(외계인 앞)→윗줄 칸으로 같이 날아가 고정
function playOffer(finishedIndex, afterFill) {
  const stageId = STAGE_IDS[finishedIndex];
  const alienE = history.findLast(e => e.who === "alien" && e.stage === stageId);
  const userE = history.findLast(e => e.who === "user" && e.stage === stageId);
  const cells = document.querySelectorAll("#tile-record .record-cell");
  const topCell = cells[finishedIndex], botCell = cells[4 + finishedIndex]; // 윗줄 0~3, 아랫줄 4~7
  const a = alienExpr.getBoundingClientRect();
  const b = (thinkEl && !thinkEl.hidden) ? thinkEl.getBoundingClientRect() : a; // 말풍선 위치(숨겨졌으면 외계인)
  hideThink();
  if (reduceMotion || !topCell || !botCell) { afterFill(); return; }

  const jobs = [];
  if (alienE) jobs.push(flyTile((c) => {
    const tx = textureFor(alienE.scores.hs);
    renderTile(c, colorFor(alienE.scores, tx), tx, 12345);
  }, a.left + a.width / 2, a.top + a.height * 0.6, topCell));
  if (userE?.signal?.color) jobs.push(flyTile((c) =>
    renderTile(c, userE.signal.color, userE.signal.texture, 54321),
    b.left + b.width / 2, b.top + b.height / 2, botCell));

  if (!jobs.length) { afterFill(); return; }
  Promise.all(jobs).then(afterFill);
}

function updateGameState(data) {
  const prevIndex = currentStageIndex;
  if (data.state) currentState = data.state;
  if (data.stage) {
    currentStageId = data.stage.id;
    currentStageIndex = data.stage.index;
    document.body.dataset.stage = data.stage.id; // 단계별 배경 (style.css)
    stageNames[data.stage.id] = data.stage.name;
  }
  if (data.dish) currentDishId = data.dish.id;

  // 단계 종료 판정: done = 마지막 단계가 끝 / advanced = 직전 단계가 끝
  let finishedIndex = -1;
  if (currentState?.done) finishedIndex = currentStageIndex;
  else if (data.stage?.advanced) finishedIndex = prevIndex;
  if (finishedIndex >= 0) undoStack = []; // 단계가 바뀌면 되돌리기 스냅샷 비움(이전 단계로 안 감)
  refreshUndo();

  if (finishedIndex >= 0) {
    // 끝난 단계 타일을 내밀고(날아가고) 나서야 그 칸을 채우고 다음 포즈로 바꾼다
    playOffer(finishedIndex, () => {
      renderTileRecord();
      if (currentState?.done) {
        if (data.result && resultOverlayEl) {
          if (resultImageEl) resultImageEl.src = data.result.image;
          resultSuccess = data.result.success;
          resultOverlayEl.hidden = false;
          showRecord();
        }
        sendButton.disabled = true;
        hideThink();
      } else {
        showAlien(data); // 그다음 다음 단계 포즈 (첫 추측 타일은 화면에 안 보임)
        updateThink();   // 새 단계 진행 중 → 말풍선 다시
      }
    });
  } else {
    showAlien(data);
    renderTileRecord();
    updateThink();
  }
}

function addAlienToHistory(data) {
  if (data.alien?.scores && data.stage) {
    history.push({ who: "alien", stage: data.stage.id, message: data.alien.word || "", scores: data.alien.scores });
  }
}

async function startCooking() {
  history = [];
  undoStack = [];
  awaiting = false;
  refreshUndo();
  if (resultOverlayEl) resultOverlayEl.hidden = true;
  sendButton.disabled = false;

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
    addAlienToHistory(data);
    updateGameState(data);
  } catch (error) {
    console.error(error);
    sendButton.disabled = true;
  }
}

restartBtn?.addEventListener("click", () => {
  startCooking();
});

// 보내기(✓): 색·질감 타일만 보낸다. 글은 고정 문자열 "타일" (app.py는 그대로)
sendButton.addEventListener("click", async () => {
  const signal = window.noizilian?.getSignal() ?? null;
  if (!signal || sendButton.disabled) return;

  // 보내기 직전 스냅샷: 이전 state·history 길이·단계·보낸 타일 값(취소 시 선택기 복원)
  undoStack.push({
    state: currentState ? structuredClone(currentState) : null,
    stageId: currentStageId,
    stageIndex: currentStageIndex,
    historyLen: history.length,
    signal: structuredClone(signal),
  });
  const sentStage = currentStageId;
  awaiting = true;
  sendButton.disabled = true;
  refreshUndo();

  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: "타일",
        username: shell.dataset.username || "사용자",
        signal: { color: signal.color, texture: signal.texture, seed: signal.seed },
        state: currentState || undefined,
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "답변을 받지 못했습니다.");
    if (typeof data.reply !== "string") throw new Error("서버 응답 형식이 올바르지 않습니다.");
    if (sentStage) {
      history.push({
        who: "user", stage: sentStage, message: "타일",
        signal: { color: signal.color, texture: signal.texture, seed: signal.seed }, scores: signal.scores,
      });
    }
    addAlienToHistory(data);
    updateGameState(data);
  } catch (error) {
    console.error(error);
    undoStack.pop(); // 교환이 일어나지 않았으니 방금 스냅샷 취소
  } finally {
    awaiting = false;
    if (!currentState?.done) sendButton.disabled = false;
    refreshUndo();
  }
});

// 되돌리기(↺): 방금 보낸 타일을 취소 — history에서 빼고 확신·단계를 그 전으로, 선택기는 그 타일 값으로
undoBtn?.addEventListener("click", () => {
  if (!undoStack.length || awaiting || currentState?.done) return;
  const snap = undoStack.pop();
  currentState = snap.state;
  currentStageId = snap.stageId;
  currentStageIndex = snap.stageIndex;
  history.length = snap.historyLen; // 방금 보낸 내 타일 + 외계인 응답 제거
  window.noizilian?.restore(snap.signal); // 선택기를 취소한 타일 값으로 (조금 고쳐 다시 보낼 수 있게)
  renderTileRecord();
  updateThink();
  refreshUndo();
});

// ── 7. 골든 레코드 ──────────────────────────────────────────
// 주고받은 타일마다 무작위 기호 3개(한 묶음)를 바깥에서 안쪽으로 도는 나선 홈을 따라 새긴다.
// 묶음에 마우스를 올리면 ① 그 타일 값으로 만든 무작위 3음 소리 ② 타일을 말로 옮긴 대사(OpenAI)
// ③ 외계인 대사면 대사와 가장 비슷한 외계인 그림(서버가 임베딩으로 고름)

const recordCanvas = document.getElementById("record-canvas");
const recordTip = document.getElementById("record-tip");
const PER_TURN = 12; // 한 바퀴에 들어가는 타일 수
const SYMBOLS_PER_TILE = 3;
let symbols = []; // {x, y, size, angle, glyph, tile}
let motifs = []; // 타일마다 무작위 3음 패턴
let lines = null; // 타일마다 {text, image} — null이면 아직 만드는 중
let hovered = -1; // 마우스가 올라간 타일 번호
let recordToken = 0;
let audio = null;

const RECORD_SIZE = 600; // 레코드 기준 좌표. 실제 캔버스 픽셀은 fitCanvases가 화면에 맞추고 drawRecord가 늘려 그린다

function recordGeometry() {
  const S = RECORD_SIZE;
  return { S, band: S * 0.035, pitch: S * 0.045, outer: S * 0.44, step: (2 * Math.PI) / PER_TURN };
}

function arcOf(i) {
  const { band, pitch, outer, step } = recordGeometry();
  const start = -Math.PI / 2 + i * step;
  return { r: outer - (i * pitch) / PER_TURN - band / 2, start, end: start + step - 0.06 };
}

/** 무작위 기호: 고리·막대·지그재그·점·반원 중 2~3개를 겹친다 (단위 좌표 -1~1) */
function randomGlyph(rand) {
  const kinds = ["ring", "bar", "zigzag", "dot", "half"];
  return Array.from({ length: 2 + Math.floor(rand() * 2) }, () => {
    const kind = kinds[Math.floor(rand() * kinds.length)];
    const a = rand() * Math.PI * 2;
    if (kind === "ring") return { kind, r: 0.4 + rand() * 0.6 };
    if (kind === "dot") return { kind, x: Math.cos(a) * 0.6, y: Math.sin(a) * 0.6 };
    if (kind === "half") return { kind, r: 0.5 + rand() * 0.4, a };
    if (kind === "bar") return { kind, a };
    const n = 3 + Math.floor(rand() * 2);
    return { kind, points: Array.from({ length: n }, (_, j) => [-1 + (2 * j) / (n - 1), rand() * 2 - 1]) };
  });
}

/** 무작위 3음 패턴: 음계 안의 음·옥타브 뛰기·간격·길이를 매번 다르게 */
function randomMotif() {
  const pick = (list) => list[Math.floor(Math.random() * list.length)];
  let at = 0;
  return Array.from({ length: SYMBOLS_PER_TILE }, () => {
    const note = { degree: Math.floor(Math.random() * 5), octave: pick([0, 0, 0, 1, -1]), at, length: 0.25 + Math.random() * 0.45 };
    at += pick([0.12, 0.18, 0.25, 0.35]);
    return note;
  });
}

function buildSymbols() {
  const { S, band } = recordGeometry();
  symbols = [];
  motifs = history.map(randomMotif);
  history.forEach((entry, i) => {
    const arc = arcOf(i);
    for (let k = 0; k < SYMBOLS_PER_TILE; k++) {
      const angle = arc.start + ((k + 0.5) * (arc.end - arc.start)) / SYMBOLS_PER_TILE;
      symbols.push({
        x: S / 2 + arc.r * Math.cos(angle),
        y: S / 2 + arc.r * Math.sin(angle),
        size: band * 0.5,
        angle,
        glyph: randomGlyph(mulberry32(Math.floor(Math.random() * 2 ** 31))),
        tile: i,
      });
    }
  });
}

function drawGlyph(ctx, glyph) {
  ctx.beginPath();
  for (const part of glyph) {
    if (part.kind === "ring") {
      ctx.moveTo(part.r, 0);
      ctx.arc(0, 0, part.r, 0, Math.PI * 2);
    } else if (part.kind === "half") {
      ctx.moveTo(part.r * Math.cos(part.a), part.r * Math.sin(part.a));
      ctx.arc(0, 0, part.r, part.a, part.a + Math.PI);
    } else if (part.kind === "bar") {
      ctx.moveTo(-Math.cos(part.a), -Math.sin(part.a));
      ctx.lineTo(Math.cos(part.a), Math.sin(part.a));
    } else if (part.kind === "dot") {
      ctx.moveTo(part.x + 0.12, part.y);
      ctx.arc(part.x, part.y, 0.12, 0, Math.PI * 2);
    } else {
      part.points.forEach(([x, y], j) => (j ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    }
  }
  ctx.stroke();
}

function drawRecord() {
  const ctx = recordCanvas.getContext("2d");
  const { S } = recordGeometry();
  ctx.setTransform(recordCanvas.width / S, 0, 0, recordCanvas.width / S, 0, 0);
  ctx.clearRect(0, 0, S, S);
  ctx.lineCap = ctx.lineJoin = "round";
  symbols.forEach((sym) => {
    ctx.save();
    ctx.translate(sym.x, sym.y);
    ctx.rotate(sym.angle + Math.PI / 2); // 홈 방향으로 눕혀 새긴 느낌
    ctx.scale(sym.size, sym.size);
    ctx.lineWidth = 2.2 / sym.size;
    ctx.shadowColor = "rgb(0 0 0 / 60%)";
    ctx.shadowBlur = 3;
    ctx.strokeStyle = sym.tile === hovered ? "#fff" : "rgb(255 236 170 / 90%)"; // 원본 레코드의 새긴 선 색
    drawGlyph(ctx, sym.glyph);
    ctx.restore();
  });
}

/** 커서가 있는 묶음(타일) 번호, 없으면 -1. 기호 3개가 놓인 홈 구간 전체를 한 히트박스로 본다 */
function hitTile(event) {
  const rect = recordCanvas.getBoundingClientRect();
  const { S, band } = recordGeometry();
  const x = ((event.clientX - rect.left) * S) / rect.width - S / 2;
  const y = ((event.clientY - rect.top) * S) / rect.height - S / 2;
  const r = Math.hypot(x, y);
  const angle = Math.atan2(y, x);
  const reach = band * 0.7; // 기호 반지름(band × 0.5)보다 조금 넉넉하게
  return history.findIndex((_, i) => {
    const arc = arcOf(i);
    const d = (((angle - arc.start) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI);
    return d <= arc.end - arc.start && Math.abs(r - arc.r) <= reach;
  });
}

/** 타일 점수 + 무작위 패턴으로 3음을 낸다. [앱 설정] 소리 대응은 논문이 아니라 우리가 정한 것:
 *  무거움–가벼움 → 음높이, 따뜻함–차가움 → 장·단조 음계와 음색 밝기, 단단함–부드러움 → 파형과 시작 속도. */
function playTile(scores, motif) {
  audio ??= new AudioContext();
  audio.resume();
  const scale = scores.wc < 0 ? [0, 2, 4, 7, 9] : [0, 3, 5, 7, 10]; // 따뜻함 = 장조 5음, 차가움 = 단조 5음
  const root = 262 * 2 ** scores.hl;
  const attack = scores.hs > 0 ? 0.08 : 0.01; // 부드러울수록 천천히 시작
  for (const note of motif) {
    const start = audio.currentTime + note.at;
    const osc = audio.createOscillator();
    osc.type = scores.hs < -0.33 ? "square" : scores.hs > 0.33 ? "sine" : "triangle";
    osc.frequency.value = root * 2 ** (note.octave + scale[note.degree] / 12);
    const filter = audio.createBiquadFilter();
    filter.frequency.value = 1800 * 2 ** -scores.wc; // 따뜻할수록(음수) 밝게
    const gain = audio.createGain();
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.15, start + attack);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + note.length);
    osc.connect(filter).connect(gain).connect(audio.destination);
    osc.start(start);
    osc.stop(start + note.length + 0.05);
  }
}

// 대사는 타일 단위. 외계인 대사에만 그림
function showTip(event, tile) {
  const item = lines?.[tile];
  const line = document.createElement("q");
  line.textContent = item?.text ?? "대사를 만드는 중…"; // 아직 안 온 타일
  const img = document.createElement("img");
  img.alt = "";
  img.hidden = !item?.image;
  if (item?.image) img.src = item.image;
  recordTip.replaceChildren(line, img);
  recordTip.hidden = false;

  const box = recordTip.parentElement.getBoundingClientRect();
  const px = event.clientX - box.left;
  const py = event.clientY - box.top;
  // 커서 반대쪽에 띄워 레코드 밖으로 넘치지 않게
  recordTip.style.left = `${px < box.width / 2 ? px + 14 : px - recordTip.offsetWidth - 14}px`;
  recordTip.style.top = `${py < box.height / 2 ? py + 14 : py - recordTip.offsetHeight - 14}px`;
}

// pointer = 마우스·펜·터치. 터치는 누를 때 한 번
function onRecordPointer(event) {
  const tile = hitTile(event);
  if (tile < 0) {
    recordTip.hidden = true;
    recordCanvas.style.cursor = "";
  } else {
    showTip(event, tile);
    recordCanvas.style.cursor = "pointer";
    if (tile !== hovered) playTile(history[tile].scores, motifs[tile]);
  }
  if (tile !== hovered) {
    hovered = tile;
    drawRecord();
  }
}
recordCanvas?.addEventListener("pointermove", onRecordPointer);
recordCanvas?.addEventListener("pointerdown", onRecordPointer);
recordCanvas?.addEventListener("pointerleave", () => {
  recordTip.hidden = true;
  hovered = -1;
  drawRecord();
});

async function showRecord() {
  if (!recordCanvas) return;
  const token = ++recordToken;
  recordTip.hidden = true;
  hovered = -1;
  lines = null;
  buildSymbols();
  fitCanvases(); // 결과 화면이 막 보여서 레코드 크기를 이제 알 수 있다 (drawRecord 포함)
  if (!history.length) return;
  try {
    const response = await fetch("/api/record", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        dish: currentDishId,
        success: resultSuccess,
        entries: history.map(({ who, stage, message, signal, scores }) =>
          who === "user" ? { who, stage, message, signal } : { who, stage, message, scores }),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error?.message || "대사를 받지 못했습니다.");
    if (token !== recordToken) return; // 그 사이 다시 시작함
    lines = data.lines;
    if (data.source !== "openai") console.warn("레코드 대사: 준비된 대사 사용", data.source); // 화면엔 안 보임
  } catch (error) {
    if (token !== recordToken) return;
    lines = [];
    console.warn("레코드 대사를 불러오지 못함", error); // "Failed to fetch" = 서버와 연결이 끊김
  }
}

// ── 8. 반응형 화면 ──────────────────────────────────────────
// 기준은 CSS와 같은 orientation 하나. 가로 = 고정 스테이지를 배율로 맞춤(남는 곳은 여백), 세로 = CSS가 위아래로 쌓음(배율 1).
// 클릭 좌표(색 네모·레코드)는 getBoundingClientRect 비율로 계산하므로 배율이 바뀌어도 맞는다.
const stageEl = document.querySelector(".stage");
const portrait = window.matchMedia("(orientation: portrait)");
let stageScale = 1;

function fitStage() {
  if (!stageEl) return;
  const css = getComputedStyle(stageEl);
  const w = parseFloat(css.getPropertyValue("--stage-w"));
  const h = parseFloat(css.getPropertyValue("--stage-h"));
  stageScale = portrait.matches ? 1 : Math.min(window.innerWidth / w, window.innerHeight / h);
  stageEl.style.setProperty("--stage-scale", stageScale);
  fitCanvases();
}

/** 캔버스 실제 픽셀 = 보이는 크기(CSS px) × 스테이지 배율 × devicePixelRatio (흐려지지 않게). 바뀌었으면 true */
function fitCanvas(canvas, scale, maxWidth) {
  if (!canvas?.clientWidth) return false; // 안 보이는 중
  const w = Math.min(maxWidth, Math.round(canvas.clientWidth * scale * window.devicePixelRatio));
  const h = Math.round((w * canvas.clientHeight) / canvas.clientWidth);
  if (canvas.width === w && canvas.height === h) return false;
  canvas.width = w;
  canvas.height = h;
  return true;
}

function fitCanvases() {
  // shortcut: 색 네모·미리보기는 픽셀마다 다시 계산하므로 너비 1024·256px에서 멈춘다. 끌 때 느리지 않으면 더 키워도 된다
  const color = fitCanvas(document.getElementById("color-canvas"), stageScale, 1024);
  const tile = fitCanvas(document.getElementById("preview-tile"), stageScale, 256);
  if (color || tile) window.noizilian?.redraw();
  if (recordCanvas && !resultOverlayEl?.hidden) { // 결과 화면은 스테이지 밖이라 배율 1
    fitCanvas(recordCanvas, 1, 1600);
    drawRecord();
  }
}

let fitQueued = false;
function queueFit() { // 창 크기 변경·회전이 몰려도 한 프레임에 한 번만
  if (fitQueued) return;
  fitQueued = true;
  requestAnimationFrame(() => { fitQueued = false; fitStage(); });
}
window.addEventListener("resize", queueFit);
window.addEventListener("orientationchange", queueFit);
portrait.addEventListener("change", queueFit);
fitStage();

// 페이지 시작 시 요리 시작 API 호출
if (shell) {
  startCooking();
}

