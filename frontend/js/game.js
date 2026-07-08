/* ============================================================
   game.js — Board rendering, card rendering, game state display
   ============================================================ */

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
const PAWN_COLORS = ["#2d7a45", "#4a90d9", "#e05252", "#f5c842"];

// ---- Board SVG ----
export function renderBoard(container, players, boardSize = BOARD_SIZE) {
  const W = 300, H = 300, cx = W / 2, cy = H / 2;
  const r = 120;
  const spaceAngle = (2 * Math.PI) / boardSize;

  let svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;

  // Track circle
  svg += `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#c9b882" stroke-width="3"/>`;

  // Spaces
  for (let i = 0; i < boardSize; i++) {
    const angle = i * spaceAngle - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="8" fill="#fff" stroke="#c9b882" stroke-width="1.5"/>`;
    // Space number
    svg += `<text x="${x.toFixed(1)}" y="${(y + 1).toFixed(1)}" text-anchor="middle" dominant-baseline="middle" font-size="5" fill="#aaa">${i}</text>`;
  }

  // Home spaces (larger, colored)
  const homes = players.map(p => p.home_position);
  players.forEach((p, idx) => {
    const angle = p.home_position * spaceAngle - Math.PI / 2;
    const x = cx + r * Math.cos(angle);
    const y = cy + r * Math.sin(angle);
    svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="10" fill="${PAWN_COLORS[idx]}" opacity="0.3" stroke="${PAWN_COLORS[idx]}" stroke-width="2"/>`;
  });

  // Pawns
  players.forEach((p, idx) => {
    if (p.eliminated) return;
    const pos = p.position !== undefined ? p.position : 0;
    const angle = pos * spaceAngle - Math.PI / 2;
    const offset = idx * 5 - ((players.length - 1) * 2.5); // spread multiple pawns
    const x = cx + (r + offset) * Math.cos(angle);
    const y = cy + (r + offset) * Math.sin(angle);
    svg += `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="9" fill="${PAWN_COLORS[idx]}" stroke="#fff" stroke-width="2"/>`;
    svg += `<text x="${x.toFixed(1)}" y="${(y + 1).toFixed(1)}" text-anchor="middle" dominant-baseline="middle" font-size="8" fill="#fff" font-weight="bold">${(p.name || "?")[0].toUpperCase()}</text>`;
  });

  // Center label
  svg += `<text x="${cx}" y="${cy - 8}" text-anchor="middle" font-size="14" font-weight="bold" fill="#2d7a45">TAG!</text>`;
  svg += `<text x="${cx}" y="${cy + 10}" text-anchor="middle" font-size="8" fill="#7a6a45">The Playground Chase</text>`;

  svg += `</svg>`;
  container.innerHTML = svg;
}

// ---- Card element ----
export function makeCardEl(cardName, copiesInPlay = 0, opts = {}) {
  const { selectable = false, faceDown = false, onClick = null } = opts;

  const el = document.createElement("div");
  el.className = "card";
  el.dataset.type = cardName;

  if (faceDown) {
    el.classList.add("face-down");
    el.innerHTML = `<span style="color:#7ec87e;font-size:1.8rem;">🂠</span>`;
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

  if (selectable && onClick) {
    el.addEventListener("click", () => onClick(cardName, el));
  }
  if (!selectable) el.classList.add("disabled");

  return el;
}

// ---- Render a player's hand ----
export function renderHand(container, cards, opts = {}) {
  container.innerHTML = "";
  if (!cards || cards.length === 0) {
    container.innerHTML = `<span style="color:#aaa;font-size:.8rem;">Empty hand</span>`;
    return;
  }
  cards.forEach(name => {
    const el = makeCardEl(name, 0, opts);
    container.appendChild(el);
  });
}

// ---- Render recruited cards (stacked by type) ----
export function renderRecruited(container, recruited) {
  container.innerHTML = "";
  if (!recruited || recruited.length === 0) {
    container.innerHTML = `<span style="color:#aaa;font-size:.8rem;">No cards recruited</span>`;
    return;
  }

  // Group by name
  const groups = {};
  recruited.forEach(name => {
    groups[name] = (groups[name] || 0) + 1;
  });

  Object.entries(groups).forEach(([name, count]) => {
    const wrapper = document.createElement("div");
    wrapper.style.position = "relative";
    wrapper.style.display = "inline-block";
    wrapper.style.marginRight = "12px";
    wrapper.style.marginBottom = "12px";

    const card = makeCardEl(name, count, { selectable: false });
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

// ---- Pending play area ----
export function renderPendingPlay(container, pendingPlay, isRecruiting) {
  container.innerHTML = "";
  if (!pendingPlay) return;

  const label = document.createElement("p");
  label.style.fontWeight = "700";
  label.style.marginBottom = "8px";
  label.textContent = isRecruiting ? "Choose a card to recruit:" : "Cards in play:";
  container.appendChild(label);

  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "12px";
  row.style.justifyContent = "center";

  // Face-up card
  const upWrap = document.createElement("div");
  upWrap.style.textAlign = "center";
  upWrap.appendChild(makeCardEl(pendingPlay.face_up, 0, {
    selectable: isRecruiting,
    onClick: isRecruiting ? () => {} : null,
  }));
  const upLabel = document.createElement("small");
  upLabel.textContent = "Face-up";
  upWrap.appendChild(upLabel);

  // Face-down card
  const downWrap = document.createElement("div");
  downWrap.style.textAlign = "center";
  downWrap.appendChild(makeCardEl(
    isRecruiting ? pendingPlay.face_down : "?",
    0,
    { selectable: isRecruiting, faceDown: !isRecruiting }
  ));
  const downLabel = document.createElement("small");
  downLabel.textContent = "Face-down";
  downWrap.appendChild(downLabel);

  row.appendChild(upWrap);
  row.appendChild(downWrap);
  container.appendChild(row);
}
