/* ============================================================
   game.js — Board rendering, card rendering, animated pawns
   ============================================================ */

const SVG_NS = "http://www.w3.org/2000/svg";
const BOARD_SIZE = 24;

// Map card name → SVG asset slug
const CARD_ART = {
  "Enforcer":     "enforcer",
  "Double Agent": "double-agent",
  "Codebreaker":  "codebreaker",
  "Saboteur":     "saboteur",
  "Daredevil":    "daredevil",
  "Sentinel":     "sentinel",
  "Sidekick":     "sidekick",
  "Mole":         "mole",
};

const CARD_VALUES_MAP = {
  "Enforcer":     ["+1", "+2", "+3"],
  "Double Agent": ["−1", "+6", "−1"],
  "Codebreaker":  ["0",  "0",  "WIN"],
  "Saboteur":     ["−1", "−1", "−2"],
  "Daredevil":    ["+2", "+3", "LOSE"],
  "Sentinel":     ["0",  "+2", "+6"],
  "Sidekick":     ["+4", "+4", "+4"],
  "Mole":         ["−3", "−3", "−3"],
};

export const PAWN_COLORS = ["#2d7a45", "#4a90d9", "#e05252", "#f5c842"];

// ────────────────────────────────────────────────────────────────────────────
// Board — rectangular neighborhood path (7 spaces per side, 24 total)
// ────────────────────────────────────────────────────────────────────────────

let _boardContainer = null;
let _boardSvg = null;
const _meeples = new Map(); // player_id → { g, circle, ring, text, prevPos, colorIdx }

function _svgEl(tag, attrs = {}, parent = null) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  parent?.appendChild(el);
  return el;
}

// 24 spaces on a rectangle: 7 per side (corners shared)
// Indices 0,6,12,18 are the four corners (top-left, top-right, bottom-right, bottom-left)
function _spaceCoords(i, W = 300, H = 300, pad = 22) {
  const perSide = 6; // 6 segments → 7 points per side, minus shared corners = 6 unique per side
  const side = Math.floor(i / perSide); // 0=top, 1=right, 2=bottom, 3=left
  const t = (i % perSide) / perSide;
  const x0 = pad, y0 = pad, x1 = W - pad, y1 = H - pad;

  switch (side) {
    case 0: return { x: x0 + t * (x1 - x0), y: y0 };           // top: left→right
    case 1: return { x: x1, y: y0 + t * (y1 - y0) };           // right: top→bottom
    case 2: return { x: x1 - t * (x1 - x0), y: y1 };           // bottom: right→left
    case 3: return { x: x0, y: y1 - t * (y1 - y0) };           // left: bottom→top
    default: return { x: x0, y: y0 };
  }
}

export function renderBoard(container, players, boardSize = BOARD_SIZE) {
  const playersMismatch = !players.every(p => _meeples.has(p.id));
  if (!_boardSvg || !container.contains(_boardSvg) || playersMismatch) {
    _createBoard(container, players, boardSize);
    _boardContainer = container;
  } else {
    _updateMeeples(players, boardSize);
  }
}

function _createBoard(container, players, boardSize) {
  const W = 300, H = 300;

  container.innerHTML = "";
  _meeples.clear();

  const svg = _svgEl("svg", { viewBox: `0 0 ${W} ${H}`, id: "board-svg" });
  svg.style.cssText = "width:100%;height:100%;overflow:visible;display:block;";

  // ── Background ──────────────────────────────────────────────────────────
  // Grass / park fill
  _svgEl("rect", { x: 0, y: 0, width: W, height: H, fill: "#4a8c5c", rx: 8 }, svg);
  // Inner path area (street/sidewalk)
  _svgEl("rect", { x: 18, y: 18, width: W - 36, height: H - 36, fill: "#7ab87a", rx: 6 }, svg);
  // Center block (buildings / park)
  _svgEl("rect", { x: 52, y: 52, width: W - 104, height: H - 104, fill: "#5a9e6e", rx: 4 }, svg);

  // ── Decorative center block ──────────────────────────────────────────────
  // Park bench, trees, decorative elements
  _svgEl("circle", { cx: 90,  cy: 90,  r: 14, fill: "#2d6e3e", opacity: ".5" }, svg);
  _svgEl("circle", { cx: 210, cy: 90,  r: 14, fill: "#2d6e3e", opacity: ".5" }, svg);
  _svgEl("circle", { cx: 90,  cy: 210, r: 14, fill: "#2d6e3e", opacity: ".5" }, svg);
  _svgEl("circle", { cx: 210, cy: 210, r: 14, fill: "#2d6e3e", opacity: ".5" }, svg);

  // Center title area
  const titleBg = _svgEl("rect", { x: 100, y: 108, width: 100, height: 54, fill: "rgba(0,0,0,.25)", rx: 8 }, svg);
  const t1 = _svgEl("text", {
    x: 150, y: 132, "text-anchor": "middle",
    "font-size": "20", "font-weight": "900", fill: "#f5c842",
    "font-family": "Fredoka One, cursive",
    "letter-spacing": "-0.5",
  }, svg);
  t1.textContent = "TAG!";
  const t2 = _svgEl("text", {
    x: 150, y: 148, "text-anchor": "middle",
    "font-size": "6.5", fill: "rgba(255,255,255,.75)",
    "font-family": "Nunito, sans-serif",
  }, svg);
  t2.textContent = "The Playground Chase";

  // ── Track path (sidewalk border) ─────────────────────────────────────────
  const pad = 22;
  // Outer track rectangle
  _svgEl("rect", {
    x: pad, y: pad, width: W - pad * 2, height: H - pad * 2,
    fill: "none", stroke: "#c9b882", "stroke-width": "3.5",
    rx: 4, "stroke-dasharray": "none",
  }, svg);
  // Inner track rectangle (inner edge of the path)
  _svgEl("rect", {
    x: pad + 16, y: pad + 16, width: W - (pad + 16) * 2, height: H - (pad + 16) * 2,
    fill: "none", stroke: "#c9b882", "stroke-width": "1.5", opacity: ".5",
    rx: 3,
  }, svg);

  // ── Street markings (dashes in the corners) ─────────────────────────────
  const cornerSize = 12;
  [[pad, pad], [W - pad, pad], [W - pad, H - pad], [pad, H - pad]].forEach(([cx, cy]) => {
    _svgEl("rect", { x: cx - cornerSize / 2, y: cy - cornerSize / 2, width: cornerSize, height: cornerSize,
      fill: "#daa520", opacity: ".4", rx: 2 }, svg);
  });

  // ── Spaces ───────────────────────────────────────────────────────────────
  const homeSet = new Set(players.map(p => p.home_position));

  for (let i = 0; i < boardSize; i++) {
    const { x, y } = _spaceCoords(i, W, H, pad);
    const isHome = homeSet.has(i);
    const homePlayerIdx = isHome ? players.findIndex(p => p.home_position === i) : -1;
    const spaceColor = isHome ? PAWN_COLORS[homePlayerIdx % PAWN_COLORS.length] : null;

    if (isHome) {
      // Home space: colored flag marker
      _svgEl("circle", {
        cx: x.toFixed(1), cy: y.toFixed(1), r: "11",
        fill: spaceColor, opacity: ".25",
        stroke: spaceColor, "stroke-width": "2.5",
      }, svg);
      _svgEl("circle", {
        cx: x.toFixed(1), cy: y.toFixed(1), r: "5.5",
        fill: spaceColor, opacity: ".8",
      }, svg);
      // House icon (tiny)
      const houseGroup = _svgEl("g", { transform: `translate(${(x - 5).toFixed(1)},${(y + 12).toFixed(1)}) scale(0.35)` }, svg);
      const houseText = _svgEl("text", { x: 0, y: 0, "font-size": "22", "text-anchor": "middle" }, houseGroup);
      houseText.textContent = "🏠";
    } else {
      // Regular space: light circle with subtle shadow
      _svgEl("circle", {
        cx: x.toFixed(1), cy: y.toFixed(1), r: "7",
        fill: "#faf8f0", stroke: "#c9b882", "stroke-width": "1.5",
        opacity: ".92",
      }, svg);
    }

    // Space number (tiny, subtle)
    const numEl = _svgEl("text", {
      x: x.toFixed(1), y: (y + 0.5).toFixed(1),
      "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "5",
      fill: isHome ? spaceColor : "#888",
    }, svg);
    numEl.textContent = i;
  }

  // ── Meeple layer ─────────────────────────────────────────────────────────
  const meepleLayer = _svgEl("g", { id: "meeple-layer" }, svg);

  players.forEach((p, idx) => {
    const color = PAWN_COLORS[idx % PAWN_COLORS.length];
    const g = document.createElementNS(SVG_NS, "g");
    g.classList.add("board-meeple");
    g.setAttribute("data-player-id", p.id);

    const ring = _svgEl("circle", { cx: 0, cy: 0, r: "15", fill: "none", stroke: color, "stroke-width": "2.5", opacity: "0.3" }, g);
    const circle = _svgEl("circle", { cx: 0, cy: 0, r: "10", fill: color, stroke: "#fff", "stroke-width": "2.5" }, g);
    const text = _svgEl("text", {
      x: 0, y: 1, "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "9", fill: "#fff", "font-weight": "bold",
    }, g);
    text.textContent = (p.name || "?")[0].toUpperCase();

    meepleLayer.appendChild(g);
    _meeples.set(p.id, { g, circle, ring, text, prevPos: -1, colorIdx: idx });
  });

  container.appendChild(svg);
  _boardSvg = svg;

  // Place meeples at initial positions WITHOUT transition
  players.forEach((p, idx) => {
    const layer = _meeples.get(p.id);
    if (!layer) return;
    const pos = p.position ?? p.home_position ?? 0;
    const offset = _meepleOffset(idx, players.length);
    const { x, y } = _spaceCoords(pos, W, H, pad + offset);
    layer.g.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`;
    layer.prevPos = pos;
  });

  // Enable transitions after initial placement
  requestAnimationFrame(() => requestAnimationFrame(() => {
    _meeples.forEach(({ g }) => {
      g.style.transition = "transform 0.7s cubic-bezier(0.34,1.56,0.64,1)";
      g.style.willChange = "transform";
      g.style.filter = "drop-shadow(0 2px 8px rgba(0,0,0,0.45))";
    });
  }));

  // Board appear animation
  svg.style.opacity = "0";
  svg.style.transform = "scale(0.85) rotate(-3deg)";
  svg.style.transition = "transform 0.55s cubic-bezier(0.34,1.56,0.64,1), opacity 0.4s ease";
  requestAnimationFrame(() => requestAnimationFrame(() => {
    svg.style.opacity = "1";
    svg.style.transform = "scale(1) rotate(0deg)";
  }));
}

function _meepleOffset(idx, total) {
  // Slightly offset overlapping meeples perpendicular to the track edge
  return idx * 4 - ((total - 1) * 2);
}

function _updateMeeples(players, boardSize) {
  const W = 300, H = 300, pad = 22;

  players.forEach((p, idx) => {
    const layer = _meeples.get(p.id);
    if (!layer) return;

    if (p.eliminated) {
      layer.g.style.opacity = "0.2";
      layer.g.style.transform += " scale(0.4)";
      return;
    }

    const pos = p.position ?? 0;
    const offset = _meepleOffset(idx, players.length);
    const { x, y } = _spaceCoords(pos, W, H, pad + offset);
    layer.g.style.opacity = "1";
    layer.g.style.transform = `translate(${x.toFixed(1)}px,${y.toFixed(1)}px)`;

    if (layer.prevPos !== pos && layer.prevPos !== -1) {
      _spawnArrivalRipple(layer.g, PAWN_COLORS[layer.colorIdx]);
    }
    layer.prevPos = pos;
  });
}

function _spawnArrivalRipple(parentG, color) {
  const ripple = document.createElementNS(SVG_NS, "circle");
  ripple.setAttribute("cx", "0");
  ripple.setAttribute("cy", "0");
  ripple.setAttribute("r", "10");
  ripple.setAttribute("fill", "none");
  ripple.setAttribute("stroke", color);
  ripple.setAttribute("stroke-width", "3");
  ripple.style.cssText = `
    animation: board-ripple 0.65s cubic-bezier(0,0.5,0.5,1) forwards;
    transform-box: fill-box;
    transform-origin: center;
  `;
  parentG.appendChild(ripple);
  setTimeout(() => ripple.remove(), 700);
}

export function highlightActiveMeeple(playerId, active) {
  _meeples.forEach(({ ring }, pid) => {
    const isActive = pid === playerId && active;
    ring.setAttribute("opacity", isActive ? "0.9" : "0.2");
    ring.style.animation = isActive ? "meeple-ring-pulse 1.5s ease-in-out infinite" : "none";
  });
}

export function boardCatchFlash(container) {
  const svg = container?.querySelector("#board-svg");
  if (!svg) return;
  svg.classList.remove("board-catch");
  void svg.offsetWidth;
  svg.classList.add("board-catch");
}


// ────────────────────────────────────────────────────────────────────────────
// Card element — illustrated design with SVG art
// ────────────────────────────────────────────────────────────────────────────

export function makeCardEl(cardName, copiesInPlay = 0, opts = {}) {
  const {
    selectable = false,
    faceDown = false,
    onClick = null,
    dealAnim = false,
    pendingAnim = false,
    revealAnim = false,
  } = opts;

  const el = document.createElement("div");
  el.className = "card";
  el.dataset.type = cardName;

  if (faceDown) {
    el.classList.add("face-down");
    el.innerHTML = `<div class="card-back-inner"></div>`;
    if (pendingAnim) el.classList.add("card-pending");
    return el;
  }

  const artSlug = CARD_ART[cardName];
  const artContent = artSlug
    ? `<img src="/assets/cards/${artSlug}.svg" alt="${cardName}" loading="lazy">`
    : `<span class="card-art-fallback">?</span>`;

  const vals = CARD_VALUES_MAP[cardName] || ["?", "?", "?"];

  const valHtml = vals.map((v, i) => {
    const isCurrent = copiesInPlay > 0 && (
      (i === 0 && copiesInPlay === 1) ||
      (i === 1 && copiesInPlay === 2) ||
      (i === 2 && copiesInPlay >= 3)
    );
    const cls = isCurrent
      ? (v === "WIN" ? "v win" : v === "LOSE" ? "v lose" : "v active")
      : "v";
    return `<span class="${cls}">${v}</span>`;
  }).join("");

  el.innerHTML = `
    <div class="card-art">${artContent}</div>
    <div class="card-body">
      <div class="card-name">${cardName}</div>
      <div class="card-values">${valHtml}</div>
    </div>
  `;

  // State-based glow for recruited cards
  if (copiesInPlay === 2) {
    if (cardName === "Codebreaker") el.classList.add("codebreaker-warn");
    else if (cardName === "Daredevil") el.classList.add("daredevil-warn");
  } else if (copiesInPlay >= 3) {
    if (cardName === "Codebreaker") el.classList.add("codebreaker-win");
    else if (cardName === "Daredevil") el.classList.add("daredevil-lose");
  }

  if (dealAnim)    el.classList.add("card-deal");
  if (pendingAnim) el.classList.add("card-pending");
  if (revealAnim)  el.classList.add("card-reveal");

  if (selectable && onClick) el.addEventListener("click", () => onClick(cardName, el));
  if (!selectable) el.classList.add("disabled");

  return el;
}


// ────────────────────────────────────────────────────────────────────────────
// Hand render
// ────────────────────────────────────────────────────────────────────────────

export function renderHand(container, cards, opts = {}) {
  container.innerHTML = "";
  if (!cards || cards.length === 0) {
    container.innerHTML = `<span style="color:#aaa;font-size:.8rem;">Empty hand</span>`;
    return;
  }
  cards.forEach((name, idx) => {
    const el = makeCardEl(name, 0, { ...opts, dealAnim: true });
    el.style.animationDelay = `${idx * 70}ms`;
    container.appendChild(el);
  });
}


// ────────────────────────────────────────────────────────────────────────────
// Recruited cards render
// ────────────────────────────────────────────────────────────────────────────

export function renderRecruited(container, recruited) {
  container.innerHTML = "";
  if (!recruited || recruited.length === 0) {
    container.innerHTML = `<span style="color:#aaa;font-size:.8rem;">No cards recruited</span>`;
    return;
  }

  const groups = {};
  recruited.forEach(n => { groups[n] = (groups[n] || 0) + 1; });

  Object.entries(groups).forEach(([name, count], gIdx) => {
    const wrapper = document.createElement("div");
    wrapper.style.cssText = "position:relative;display:inline-block;margin-right:12px;margin-bottom:12px;";

    const card = makeCardEl(name, count, { dealAnim: true });
    card.style.animationDelay = `${gIdx * 60}ms`;
    wrapper.appendChild(card);

    if (count > 1) {
      const badge = document.createElement("div");
      badge.className = "stack-count";
      badge.textContent = count;
      wrapper.appendChild(badge);
    }

    container.appendChild(wrapper);
  });
}


// ────────────────────────────────────────────────────────────────────────────
// Pending play area
// ────────────────────────────────────────────────────────────────────────────

export function renderPendingPlay(container, pendingPlay, isRecruiting) {
  container.innerHTML = "";
  if (!pendingPlay) return;

  const label = document.createElement("p");
  label.style.cssText = "font-weight:700;margin-bottom:8px;";
  label.textContent = isRecruiting ? "Choose a card to recruit:" : "Cards in play:";
  container.appendChild(label);

  const row = document.createElement("div");
  row.style.cssText = "display:flex;gap:16px;justify-content:center;";

  // Face-up
  const upWrap = document.createElement("div");
  upWrap.style.textAlign = "center";
  const upCard = makeCardEl(pendingPlay.face_up, 0, {
    selectable: isRecruiting, pendingAnim: true,
    onClick: isRecruiting ? () => {} : null,
  });
  upWrap.appendChild(upCard);
  upWrap.appendChild(Object.assign(document.createElement("small"), { textContent: "Face-up" }));

  // Face-down
  const downWrap = document.createElement("div");
  downWrap.style.textAlign = "center";
  const downCard = makeCardEl(
    isRecruiting ? pendingPlay.face_down : "?",
    0,
    { selectable: isRecruiting, faceDown: !isRecruiting, pendingAnim: true }
  );
  downCard.style.animationDelay = "90ms";
  downWrap.appendChild(downCard);
  downWrap.appendChild(Object.assign(document.createElement("small"), { textContent: "Face-down" }));

  row.appendChild(upWrap);
  row.appendChild(downWrap);
  container.appendChild(row);
}
