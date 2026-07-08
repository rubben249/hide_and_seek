/* ============================================================
   game.js — Board rendering, card rendering, animated pawns
   ============================================================ */

const SVG_NS = "http://www.w3.org/2000/svg";
const BOARD_SIZE = 24;

const CARD_ICONS = {
  "Sprinter":   "🏃",
  "Prankster":  "🤡",
  "Mastermind": "🧠",
  "Blitzer":    "💥",
  "Show-off":   "🌟",
  "Lookout":    "👀",
  "Best Buddy": "🤝",
  "Snitch":     "🐀",
};

const CARD_VALUES_MAP = {
  "Sprinter":   ["+1", "+2", "+3"],
  "Prankster":  ["−1", "+6", "−1"],
  "Mastermind": ["0",  "0",  "WIN"],
  "Blitzer":    ["−1", "−1", "−2"],
  "Show-off":   ["+2", "+3", "LOSE"],
  "Lookout":    ["0",  "+2", "+6"],
  "Best Buddy": ["+4", "+4", "+4"],
  "Snitch":     ["−3", "−3", "−3"],
};

export const PAWN_COLORS = ["#2d7a45", "#4a90d9", "#e05252", "#f5c842"];

// ────────────────────────────────────────────────────────────────────────────
// Board — persistent DOM state enables CSS transitions between renders
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

function _spaceCoords(i, boardSize, r, cx, cy, radialOffset = 0) {
  const angle = (i / boardSize) * 2 * Math.PI - Math.PI / 2;
  return {
    x: cx + (r + radialOffset) * Math.cos(angle),
    y: cy + (r + radialOffset) * Math.sin(angle),
  };
}

export function renderBoard(container, players, boardSize = BOARD_SIZE) {
  // Recreate SVG if container changed, SVG is gone, or player set changed (new game)
  const playersMismatch = !players.every(p => _meeples.has(p.id));
  if (!_boardSvg || !container.contains(_boardSvg) || playersMismatch) {
    _createBoard(container, players, boardSize);
    _boardContainer = container;
  } else {
    _updateMeeples(players, boardSize);
  }
}

function _createBoard(container, players, boardSize) {
  const W = 300, H = 300, cx = W / 2, cy = H / 2, r = 118;

  container.innerHTML = "";
  _meeples.clear();

  const svg = _svgEl("svg", { viewBox: `0 0 ${W} ${H}`, id: "board-svg" });
  svg.style.cssText = "width:100%;height:100%;overflow:visible;display:block;";

  // ── Background glow ──────────────────────────────────────────────────────
  _svgEl("circle", { cx, cy, r: r + 22, fill: "none", stroke: "rgba(45,122,69,.10)", "stroke-width": "38" }, svg);

  // ── Track ────────────────────────────────────────────────────────────────
  _svgEl("circle", { cx, cy, r, fill: "none", stroke: "#c9b882", "stroke-width": "2.5", "stroke-dasharray": "2 3" }, svg);
  _svgEl("circle", { cx, cy, r, fill: "none", stroke: "#c9b882", "stroke-width": "1", opacity: "0.4" }, svg);

  // ── Spaces ───────────────────────────────────────────────────────────────
  const homeSet = new Set(players.map(p => p.home_position));

  for (let i = 0; i < boardSize; i++) {
    const { x, y } = _spaceCoords(i, boardSize, r, cx, cy);
    const isHome = homeSet.has(i);
    const homePlayerIdx = isHome ? players.findIndex(p => p.home_position === i) : -1;
    const spaceColor = isHome ? PAWN_COLORS[homePlayerIdx % PAWN_COLORS.length] : null;

    if (isHome) {
      // Home marker: larger colored circle
      _svgEl("circle", {
        cx: x.toFixed(2), cy: y.toFixed(2), r: "11",
        fill: spaceColor, opacity: "0.18",
        stroke: spaceColor, "stroke-width": "2.5",
      }, svg);
      _svgEl("circle", {
        cx: x.toFixed(2), cy: y.toFixed(2), r: "5.5",
        fill: spaceColor, opacity: "0.55",
      }, svg);
    } else {
      _svgEl("circle", {
        cx: x.toFixed(2), cy: y.toFixed(2), r: "5.5",
        fill: "#faf8f0", stroke: "#c9b882", "stroke-width": "1.5",
      }, svg);
    }

    // Space number (tiny, subtle)
    const numEl = _svgEl("text", {
      x: x.toFixed(2), y: (y + 0.5).toFixed(2),
      "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "4.5",
      fill: isHome ? spaceColor : "#bbb",
    }, svg);
    numEl.textContent = i;
  }

  // ── Center decoration ─────────────────────────────────────────────────────
  _svgEl("circle", { cx, cy, r: "40", fill: "rgba(45,122,69,.06)", stroke: "rgba(45,122,69,.18)", "stroke-width": "1.5" }, svg);
  const t1 = _svgEl("text", {
    x: cx, y: cy - 9, "text-anchor": "middle",
    "font-size": "18", "font-weight": "900", fill: "#2d7a45", "letter-spacing": "-0.5",
  }, svg);
  t1.textContent = "TAG!";
  const t2 = _svgEl("text", {
    x: cx, y: cy + 10, "text-anchor": "middle",
    "font-size": "6.5", fill: "#7a6a45",
  }, svg);
  t2.textContent = "The Playground Chase";

  // ── Meeple layer (on top of everything) ───────────────────────────────────
  const meepleLayer = _svgEl("g", { id: "meeple-layer" }, svg);

  players.forEach((p, idx) => {
    const color = PAWN_COLORS[idx % PAWN_COLORS.length];
    const g = document.createElementNS(SVG_NS, "g");
    g.classList.add("board-meeple");
    g.setAttribute("data-player-id", p.id);

    // Outer glow ring (pulses on active turn)
    const ring = _svgEl("circle", { cx: 0, cy: 0, r: "14", fill: "none", stroke: color, "stroke-width": "2", opacity: "0.3" }, g);

    // Main pawn body
    const circle = _svgEl("circle", { cx: 0, cy: 0, r: "9.5", fill: color, stroke: "#fff", "stroke-width": "2.5" }, g);

    // Initial letter label
    const text = _svgEl("text", {
      x: 0, y: 1, "text-anchor": "middle", "dominant-baseline": "middle",
      "font-size": "8.5", fill: "#fff", "font-weight": "bold",
    }, g);
    text.textContent = (p.name || "?")[0].toUpperCase();

    meepleLayer.appendChild(g);
    _meeples.set(p.id, { g, circle, ring, text, prevPos: -1, colorIdx: idx });
  });

  container.appendChild(svg);
  _boardSvg = svg;

  // Place meeples at initial positions WITHOUT transition (skip "fly from origin")
  players.forEach((p, idx) => {
    const layer = _meeples.get(p.id);
    if (!layer) return;
    const pos = p.position ?? p.home_position ?? 0;
    const offset = _meepleOffset(idx, players.length);
    const { x, y } = _spaceCoords(pos, boardSize, r + offset, cx, cy);
    layer.g.style.transform = `translate(${x.toFixed(2)}px,${y.toFixed(2)}px)`;
    layer.prevPos = pos;
  });

  // Enable transitions AFTER initial placement
  requestAnimationFrame(() => requestAnimationFrame(() => {
    _meeples.forEach(({ g }) => {
      g.style.transition = "transform 0.7s cubic-bezier(0.34,1.56,0.64,1)";
      g.style.willChange = "transform";
      g.style.filter = "drop-shadow(0 2px 6px rgba(0,0,0,0.38))";
    });
  }));

  // Board appear animation
  svg.style.opacity = "0";
  svg.style.transform = "scale(0.82) rotate(-4deg)";
  svg.style.transition = "transform 0.55s cubic-bezier(0.34,1.56,0.64,1), opacity 0.4s ease";
  requestAnimationFrame(() => requestAnimationFrame(() => {
    svg.style.opacity = "1";
    svg.style.transform = "scale(1) rotate(0deg)";
  }));
}

function _meepleOffset(idx, total) {
  return idx * 6 - ((total - 1) * 3);
}

function _updateMeeples(players, boardSize) {
  const W = 300, H = 300, cx = W / 2, cy = H / 2, r = 118;

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
    const { x, y } = _spaceCoords(pos, boardSize, r + offset, cx, cy);
    layer.g.style.opacity = "1";
    layer.g.style.transform = `translate(${x.toFixed(2)}px,${y.toFixed(2)}px)`;

    // Ripple effect when pawn arrives at a new space
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
  ripple.setAttribute("r", "9.5");
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

// Set the "active turn" ring glow on the active pawn
export function highlightActiveMeeple(playerId, active) {
  _meeples.forEach(({ ring }, pid) => {
    const isActive = pid === playerId && active;
    ring.setAttribute("opacity", isActive ? "0.85" : "0.2");
    ring.style.animation = isActive ? "meeple-ring-pulse 1.5s ease-in-out infinite" : "none";
  });
}

// Flash board when catch happens
export function boardCatchFlash(container) {
  const svg = container?.querySelector("#board-svg");
  if (!svg) return;
  svg.classList.remove("board-catch");
  void svg.offsetWidth;
  svg.classList.add("board-catch");
}


// ────────────────────────────────────────────────────────────────────────────
// Card element
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
    el.innerHTML = `<span style="color:#7ec87e;font-size:1.8rem;">🂠</span>`;
    if (pendingAnim) el.classList.add("card-pending");
    return el;
  }

  const icon = CARD_ICONS[cardName] || "❓";
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
    <div class="card-name">${cardName}</div>
    <div class="card-icon">${icon}</div>
    <div class="card-values">${valHtml}</div>
  `;

  // State-based glow for recruited cards
  if (copiesInPlay === 2) {
    if (cardName === "Mastermind") el.classList.add("mastermind-warn");
    else if (cardName === "Show-off") el.classList.add("showoff-warn");
  } else if (copiesInPlay >= 3) {
    if (cardName === "Mastermind") el.classList.add("mastermind-win");
    else if (cardName === "Show-off") el.classList.add("showoff-lose");
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
