/* ============================================================
   app.js — Main controller: screen routing, API calls, game flow
   ============================================================ */
import { renderBoard, renderHand, renderRecruited, makeCardEl, highlightActiveMeeple, boardCatchFlash } from "./game.js";
import { GameSocket } from "./ws.js";

const API = "";  // same origin

// ---- State ----
let gameId = null;
let myPlayerId = null;
let gameState = null;
let selectedFaceUp = null;
let selectedFaceDown = null;
let socket = null;
let onlineMyToken = null;
let onlineMyPlayerId = null;

// ---- Auth ----
let authToken = localStorage.getItem("tag_token") || null;
let authUsername = localStorage.getItem("tag_username") || null;

function _saveAuth(token, username) {
  authToken = token; authUsername = username;
  localStorage.setItem("tag_token", token);
  localStorage.setItem("tag_username", username);
}
function _clearAuth() {
  authToken = null; authUsername = null;
  localStorage.removeItem("tag_token");
  localStorage.removeItem("tag_username");
}

function updateAuthUI() {
  const greeting   = document.getElementById("user-greeting");
  const btnSignIn  = document.getElementById("btn-auth-open");
  const btnLb      = document.getElementById("btn-leaderboard");
  const btnLogout  = document.getElementById("btn-logout");
  const soloName   = document.getElementById("solo-name");
  const onlineName = document.getElementById("online-name");
  if (authUsername) {
    greeting?.classList.remove("hidden");
    if (greeting) greeting.textContent = `Hi, ${authUsername}!`;
    btnSignIn?.classList.add("hidden");
    btnLb?.classList.remove("hidden");
    btnLogout?.classList.remove("hidden");
    if (soloName)   soloName.value   = authUsername;
    if (onlineName) onlineName.value = authUsername;
  } else {
    greeting?.classList.add("hidden");
    btnSignIn?.classList.remove("hidden");
    btnLb?.classList.add("hidden");
    btnLogout?.classList.add("hidden");
  }
}

// ---- Timer state (local/solo mode — client-side tracking) ----
const timer = {
  interval: null,        // setInterval handle
  turnStart: null,       // Date.now() when current turn started
  activePlayerId: null,  // player whose turn clock is running
  playerTimeUsed: {},    // player_id → ms of cumulative time used
  warningsSent: {},      // player_id → [fractions already warned]
  config: null,          // timer_config from game state
  warningTimeout: null,  // hide-warning timeout handle
};

function timerFmt(seconds) {
  const s = Math.max(0, Math.ceil(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function timerStartTurn(activePlayerId, config) {
  timerStop();
  timer.config = config;
  timer.turnStart = Date.now();
  timer.activePlayerId = activePlayerId;
  timer.interval = setInterval(() => timerTick(), 1000);
  timerTick(); // immediate first draw
}

function timerStop() {
  if (timer.interval) { clearInterval(timer.interval); timer.interval = null; }
  if (timer.activePlayerId && timer.turnStart !== null) {
    const elapsed = (Date.now() - timer.turnStart) / 1000;
    timer.playerTimeUsed[timer.activePlayerId] =
      (timer.playerTimeUsed[timer.activePlayerId] || 0) + elapsed;
  }
  timer.turnStart = null;
  timer.activePlayerId = null;
}

function timerReset() {
  timerStop();
  timer.playerTimeUsed = {};
  timer.warningsSent = {};
  timer.config = null;
  timerRenderBar(null, null, null, null);
}

function timerTick() {
  if (!timer.config || timer.turnStart === null) return;
  const cfg = timer.config;
  const now = Date.now();
  const turnElapsed = (now - timer.turnStart) / 1000;
  const turnRemaining = cfg.turn_time_limit - turnElapsed;
  const pid = timer.activePlayerId;
  const playerUsed = (timer.playerTimeUsed[pid] || 0) + turnElapsed;
  const playerRemaining = cfg.player_time_limit - playerUsed;
  const gameElapsed = gameState?.timer?.game_start
    ? (now / 1000) - gameState.timer.game_start : 0;
  const gameRemaining = cfg.game_time_limit - gameElapsed;

  timerRenderBar(turnRemaining, playerRemaining, gameRemaining, pid);
  timerCheckWarnings(pid, playerUsed, playerRemaining, cfg);
}

function timerRenderBar(turnRemaining, playerRemaining, gameRemaining, activePid) {
  const turnEl = document.getElementById("timer-turn-display");
  const gameEl = document.getElementById("timer-game-display");
  const playersEl = document.getElementById("timer-players-cell");
  if (!turnEl || !gameEl || !playersEl) return;

  const cfg = timer.config;
  const threshold = cfg?.turn_countdown_threshold ?? 30;

  if (turnRemaining !== null) {
    turnEl.textContent = timerFmt(turnRemaining);
    turnEl.className = "timer-value" + (turnRemaining <= threshold ? " countdown" : "");
  } else {
    turnEl.textContent = timerFmt(cfg?.turn_time_limit ?? 120);
    turnEl.className = "timer-value";
  }

  if (gameRemaining !== null) {
    gameEl.textContent = timerFmt(gameRemaining);
  }

  // Per-player mini blocks
  if (gameState && cfg) {
    playersEl.innerHTML = "";
    gameState.players.filter(p => !p.eliminated).forEach(p => {
      const used = (timer.playerTimeUsed[p.id] || 0) + (p.id === activePid && turnRemaining !== null
        ? (cfg.turn_time_limit - Math.max(0, turnRemaining)) : 0);
      const remaining = Math.max(0, cfg.player_time_limit - used);
      const frac = used / cfg.player_time_limit;
      const cls = frac >= 0.75 ? "low" : frac >= 0.5 ? "med" : "ok";
      const block = document.createElement("div");
      block.className = "player-timer";
      block.innerHTML = `<span class="player-timer-name">${p.name.slice(0, 10)}</span>
        <span class="player-timer-value ${cls}">${timerFmt(remaining)}</span>`;
      playersEl.appendChild(block);
    });
  }
}

function timerCheckWarnings(pid, playerUsed, playerRemaining, cfg) {
  const fractions = cfg.player_warning_fractions ?? [0.25, 0.5, 0.75];
  const fracUsed = playerUsed / cfg.player_time_limit;
  const sent = timer.warningsSent[pid] || [];
  for (const frac of fractions) {
    if (fracUsed >= frac && !sent.includes(frac)) {
      sent.push(frac);
      timer.warningsSent[pid] = sent;
      const pct = Math.round(frac * 100);
      const name = gameState?.players?.find(p => p.id === pid)?.name ?? "Player";
      const isDanger = frac >= 0.75;
      showTimerWarning(
        `⏱ ${name} has used ${pct}% of their time — ${timerFmt(playerRemaining)} remaining`,
        isDanger
      );
    }
  }
}

function showTimerWarning(msg, danger = false) {
  const el = document.getElementById("timer-warning");
  if (!el) return;
  if (timer.warningTimeout) clearTimeout(timer.warningTimeout);
  el.textContent = msg;
  el.className = "timer-warning" + (danger ? " danger" : "");
  el.classList.remove("hidden");
  timer.warningTimeout = setTimeout(() => el.classList.add("hidden"), 5000);
}

// Called when server sends timer_update (online mode) or timer_warning
function timerApplyServerUpdate(msg) {
  timerRenderBar(msg.turn_remaining, msg.player_remaining, msg.game_remaining, msg.active_player_id);
  // Sync server player times into local tracking so player blocks stay accurate
  if (gameState && msg.active_player_id && msg.player_remaining !== undefined) {
    const cfg = gameState.timer_config;
    if (cfg) {
      timer.playerTimeUsed[msg.active_player_id] =
        cfg.player_time_limit - msg.player_remaining;
    }
  }
}

// Track which player's turn was last rendered (to detect turn changes)
let lastRenderedActivePlayerId = null;

// ---- Screen management ----
function show(id) {
  document.querySelectorAll(".screen").forEach(s => s.classList.remove("active"));
  document.getElementById(id)?.classList.add("active");
}

// ---- API helpers ----
async function api(path, body = null) {
  const opts = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : { method: "GET" };
  const res = await fetch(API + path, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || "API error");
  }
  return res.json();
}

// ---- Status bar ----
function setStatus(msg, color = "#2d7a45") {
  const bar = document.getElementById("status-bar");
  if (bar) { bar.textContent = msg; bar.style.background = color; }
}

// ---- Main menu ----
document.getElementById("btn-solo")?.addEventListener("click", () => show("screen-solo"));
document.getElementById("btn-local")?.addEventListener("click", () => show("screen-local"));
document.getElementById("btn-online")?.addEventListener("click", () => show("screen-online"));

// ---- Back buttons ----
document.querySelectorAll(".btn-back").forEach(btn => {
  btn.addEventListener("click", () => show("screen-menu"));
});

// ============================================================
// SOLO MODE
// ============================================================
document.getElementById("btn-start-solo")?.addEventListener("click", async () => {
  const name = document.getElementById("solo-name").value.trim() || "Player";
  const diff = document.getElementById("solo-difficulty").value;
  try {
    const data = await api("/api/solo/new", { player_name: name, difficulty: diff });
    gameId = data.game_id;
    gameState = data.state;
    myPlayerId = gameState.players.find(p => p.type === "human")?.id;
    show("screen-game");
    renderGameScreen();
  } catch (e) { alert(e.message); }
});

// ============================================================
// LOCAL MODE
// ============================================================
const localModeSelect = document.getElementById("local-mode");
const localPlayersDiv = document.getElementById("local-players-inputs");

localModeSelect?.addEventListener("change", buildLocalPlayerInputs);
function buildLocalPlayerInputs() {
  const mode = localModeSelect.value;
  const counts = { "local_1v1": 2, "local_2v2": 4, "local_2v1": 3, "local_ffa": 4 };
  const count = counts[mode] || 2;
  localPlayersDiv.innerHTML = "";
  for (let i = 0; i < count; i++) {
    const inp = document.createElement("input");
    inp.type = "text";
    inp.placeholder = `Player ${i + 1} name`;
    inp.value = `Player ${i + 1}`;
    inp.id = `local-player-${i}`;
    localPlayersDiv.appendChild(inp);
  }
}
buildLocalPlayerInputs();

document.getElementById("btn-start-local")?.addEventListener("click", async () => {
  const mode = localModeSelect.value;
  const counts = { "local_1v1": 2, "local_2v2": 4, "local_2v1": 3, "local_ffa": 4 };
  const count = counts[mode] || 2;
  const names = Array.from({ length: count }, (_, i) =>
    (document.getElementById(`local-player-${i}`)?.value.trim()) || `Player ${i + 1}`
  );
  try {
    const data = await api("/api/local/new", { mode, player_names: names });
    gameId = data.game_id;
    gameState = data.state;
    myPlayerId = gameState.players[0]?.id;
    show("screen-game");
    renderGameScreen();
  } catch (e) { alert(e.message); }
});

// ============================================================
// ONLINE MODE
// ============================================================
document.getElementById("btn-connect")?.addEventListener("click", async () => {
  const name = document.getElementById("online-name").value.trim() || "Player";

  logOnline(`Connecting as ${name}...`, "system");
  socket = new GameSocket(handleOnlineMessage, () => logOnline("Disconnected", "error"));

  try {
    await socket.connect(name);
    logOnline(`Connected! Token issued.`, "system");
    document.getElementById("online-lobby").classList.remove("hidden");
    document.getElementById("online-connect-form").classList.add("hidden");
    socket.listRooms();
  } catch (e) {
    logOnline(`Error: ${e.message}`, "error");
    socket = null;
  }
});

document.getElementById("btn-create-room")?.addEventListener("click", () => {
  const mode     = document.getElementById("online-mode").value;
  const roomName = document.getElementById("online-room-name")?.value.trim() || "";
  const roomPw   = document.getElementById("online-room-password")?.value || "";
  socket?.createRoom(mode, roomName, roomPw);
});

document.getElementById("btn-join-room")?.addEventListener("click", () => {
  const code   = document.getElementById("online-room-code")?.value.trim().toUpperCase();
  const roomPw = document.getElementById("online-join-password")?.value || "";
  if (!code) { alert("Enter a room code"); return; }
  socket?.joinRoom(code, roomPw);
});

document.getElementById("btn-start-online")?.addEventListener("click", () => {
  socket?.startGame();
});

function handleOnlineMessage(msg) {
  if (msg.type === "room_created") {
    const name = msg.room_name || msg.room_id;
    logOnline(`Room created: ${name} (code: ${msg.room_id})`, "system");
    const hdr = document.getElementById("online-room-header");
    if (hdr) hdr.textContent = `Room: ${name}`;
    const codeEl = document.getElementById("online-room-id-display");
    if (codeEl) codeEl.textContent = msg.room_id;
    const sec = document.getElementById("online-room-section");
    if (sec) sec.style.display = "";
    const list = document.getElementById("online-players-list");
    if (list) list.innerHTML = `<span style="color:#7a6a45;font-size:.85rem;">${socket.playerName}</span>`;

  } else if (msg.type === "player_joined") {
    const names = msg.players.map(p => p.name).join(", ");
    logOnline(`Players: ${names}`, "system");
    const list = document.getElementById("online-players-list");
    if (list) list.innerHTML = msg.players.map(p =>
      `<span style="display:inline-block;background:#f0e8cc;border-radius:6px;padding:2px 10px;margin:2px;font-size:.83rem;font-weight:700;">${p.name}</span>`
    ).join("");
    if (msg.ready) logOnline("Room full — host can start!", "system");

  } else if (msg.type === "room_list") {
    if (!msg.rooms?.length) {
      logOnline("No open rooms — create one!", "system");
    } else {
      msg.rooms.forEach(r => {
        const lock = r.has_password ? "🔒" : "🔓";
        const st   = r.in_game ? "[in game]" : `${r.player_count}/${r.max_players}p`;
        logOnline(`${lock} ${r.room_name || r.room_id}  code:${r.room_id}  ${st}`, "system");
      });
    }

  } else if (msg.type === "game_started") {
    gameState = msg.state;
    onlineMyPlayerId = gameState.players.find(p => p.name === socket.playerName)?.id;
    myPlayerId = onlineMyPlayerId;
    show("screen-game");
    document.getElementById("ingame-chat")?.classList.remove("hidden");
    renderGameScreen();

  } else if (msg.type === "game_state") {
    gameState = msg.state;
    renderGameScreen();

  } else if (msg.type === "game_over") {
    timerStop();
    showResult(msg.result);

  } else if (msg.type === "timer_update") {
    timerApplyServerUpdate(msg);

  } else if (msg.type === "timer_warning") {
    showTimerWarning(msg.message, msg.fraction_used >= 0.75);

  } else if (msg.type === "timer_event") {
    if (msg.event === "turn_timeout") showTimerWarning(`⏰ ${msg.message}`, true);

  } else if (msg.type === "player_disconnected") {
    const can = msg.can_rejoin ? ` (${msg.skips_remaining} turns to rejoin)` : "";
    logIngameChat(`⚠ ${msg.player_name} disconnected${can}`, "system");
    logOnline(`⚠ ${msg.player_name} disconnected${can}`, "error");

  } else if (msg.type === "player_disconnected_waiting") {
    showTimerWarning(`⏳ Waiting for ${msg.player_name}… (${msg.turn_skips}/${msg.max_skips} skips)`, false);

  } else if (msg.type === "player_reconnected") {
    logIngameChat(`✓ ${msg.player_name} reconnected`, "system");
    logOnline(`✓ ${msg.player_name} reconnected`, "system");

  } else if (msg.type === "chat_all") {
    logIngameChat(`${msg.from}: ${msg.text}`, "chat");
    logOnline(`[All] ${msg.from}: ${msg.text}`, "chat");

  } else if (msg.type === "chat_team") {
    logIngameChat(`[Team] ${msg.from}: ${msg.text}`, "team");
    logOnline(`[Team ${msg.team}] ${msg.from}: ${msg.text}`, "team");

  } else if (msg.type === "reaction") {
    logIngameChat(`${msg.emoji}  ${msg.from}`, "reaction");
    logOnline(`${msg.emoji} ${msg.from}`, "reaction");

  } else if (msg.type === "error") {
    logOnline(`Server error: ${msg.message}`, "error");

  } else {
    logOnline(JSON.stringify(msg).substring(0, 100), "system");
  }
}

function logOnline(text, cls = "") {
  const log = document.getElementById("chat-log");
  if (!log) return;
  const line = document.createElement("div");
  line.className = cls ? `msg-${cls}` : "";
  line.textContent = `> ${text}`;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

function logIngameChat(text, cls = "") {
  const log = document.getElementById("ingame-chat-log");
  if (!log) return;
  const line = document.createElement("div");
  line.className = cls ? `msg-${cls}` : "";
  line.textContent = text;
  log.appendChild(line);
  log.scrollTop = log.scrollHeight;
}

// ============================================================
// GAME SCREEN
// ============================================================
function renderGameScreen() {
  if (!gameState) return;
  const isOnline = gameState.mode === "online";
  const players = gameState.players;

  // ---- Timer management ----
  const cfg = gameState.timer_config;
  const activePlayer = players[gameState.active_player_index];
  const phase = gameState.phase;
  const isMyTurn = activePlayer?.id === myPlayerId;

  if (gameState.result || gameState.phase === "finished") {
    timerStop();
    lastRenderedActivePlayerId = null;
  } else if (!isOnline && cfg && activePlayer) {
    // Local/solo: start client-side timer when active player changes
    if (activePlayer.id !== lastRenderedActivePlayerId) {
      timerStartTurn(activePlayer.id, cfg);
      lastRenderedActivePlayerId = activePlayer.id;
    }
  } else if (isOnline) {
    // Online: timer is server-driven via timer_update events; just keep config synced
    timer.config = cfg;
    if (!lastRenderedActivePlayerId || activePlayer?.id !== lastRenderedActivePlayerId) {
      lastRenderedActivePlayerId = activePlayer?.id ?? null;
      // Send turn_ready after receiving new game state (signals animations done)
      if (socket && activePlayer) {
        socket.send("turn_ready", {});
      }
    }
  }

  // Board
  const boardContainer = document.getElementById("board-container");
  if (boardContainer) {
    renderBoard(boardContainer, players, gameState.board_size);
    if (activePlayer && !gameState.result) highlightActiveMeeple(activePlayer.id, true);
  }

  if (gameState.result) {
    showResult(gameState.result);
    return;
  }

  let statusMsg = "";
  if (phase === "play") statusMsg = isMyTurn ? `Your turn — Play 2 cards` : `${activePlayer?.name}'s turn`;
  else if (phase === "recruit") {
    const actor = players.find(p => p.id === gameState.pending_play?.actor_id);
    const isRecruiter = !isMyTurn || (gameState.pending_play?.actor_id === myPlayerId);
    statusMsg = isRecruiter
      ? `${actor?.name} played — choose a card to recruit`
      : `Waiting for opponent to recruit...`;
  }
  else if (phase === "finished") { showResult(gameState.result); return; }
  else statusMsg = `Phase: ${phase}`;

  setStatus(statusMsg);

  // Render each player's area
  renderPlayerAreas(players, isMyTurn);

  // Actions
  renderActions(phase, isMyTurn, players);

  // Deck info
  const deckInfo = document.getElementById("deck-info");
  if (deckInfo) deckInfo.textContent = `Deck: ${gameState.deck?.length ?? 0} cards`;
}

function renderPlayerAreas(players, isMyTurn) {
  const container = document.getElementById("players-area");
  if (!container) return;
  container.innerHTML = "";

  players.forEach((player, idx) => {
    const isMe = player.id === myPlayerId;
    const div = document.createElement("div");
    div.className = "player-area";
    div.style.borderColor = isMe ? "#2d7a45" : "#c9b882";

    const header = document.createElement("h3");
    header.textContent = `${player.name}${player.eliminated ? " [OUT]" : ""}${isMe ? " (You)" : ""}`;
    div.appendChild(header);

    // Position
    const posInfo = document.createElement("p");
    posInfo.style.fontSize = ".8rem";
    posInfo.style.color = "#7a6a45";
    posInfo.textContent = `Position: ${player.position} | Discards: ${player.discards_used}/${player.max_discards}`;
    div.appendChild(posInfo);

    // Hand (only show own hand or hidden cards for hot-seat)
    if (isMe || gameState.mode === "solo") {
      const handLabel = document.createElement("p");
      handLabel.style.fontWeight = "700";
      handLabel.style.fontSize = ".8rem";
      handLabel.style.marginTop = "8px";
      handLabel.textContent = "Hand:";
      div.appendChild(handLabel);

      const handDiv = document.createElement("div");
      handDiv.className = "hand";
      handDiv.id = `hand-${player.id}`;

      const hand = isMe ? player.hand : (player.hand || []).map(() => "?");
      hand.forEach((name, hIdx) => {
        const isHidden = name === "?";
        const el = isHidden
          ? makeCardEl("?", 0, { faceDown: true, dealAnim: true })
          : makeCardEl(name, 0, {
              dealAnim: true,
              selectable: isMe && isMyTurn && gameState.phase === "play",
              onClick: isMe && isMyTurn ? (n, el) => selectHandCard(n, el) : null,
            });
        el.style.animationDelay = `${hIdx * 65}ms`;
        handDiv.appendChild(el);
      });
      div.appendChild(handDiv);
    }

    // Recruited
    const recLabel = document.createElement("p");
    recLabel.style.fontWeight = "700";
    recLabel.style.fontSize = ".8rem";
    recLabel.style.marginTop = "8px";
    recLabel.textContent = "Recruited:";
    div.appendChild(recLabel);

    const recDiv = document.createElement("div");
    recDiv.className = "recruited-grid";
    // Group and render
    const groups = {};
    (player.recruited || []).forEach(n => { groups[n] = (groups[n]||0)+1; });
    Object.entries(groups).forEach(([name, cnt]) => {
      const wrap = document.createElement("div");
      wrap.style.position = "relative";
      const card = makeCardEl(name, cnt);
      wrap.appendChild(card);
      if (cnt > 1) {
        const badge = document.createElement("span");
        badge.className = "stack-count";
        badge.textContent = cnt;
        wrap.appendChild(badge);
      }
      recDiv.appendChild(wrap);
    });
    if (!Object.keys(groups).length) recDiv.innerHTML = `<span style="color:#aaa;font-size:.75rem;">None yet</span>`;
    div.appendChild(recDiv);

    container.appendChild(div);
  });
}

function renderActions(phase, isMyTurn, players) {
  const actions = document.getElementById("actions");
  const pendingArea = document.getElementById("pending-area");
  if (!actions) return;
  actions.innerHTML = "";
  if (pendingArea) pendingArea.innerHTML = "";

  if (phase === "play" && isMyTurn) {
    // Discard button
    const btnDiscard = document.createElement("button");
    btnDiscard.className = "btn btn-outline btn-sm";
    const me = players.find(p => p.id === myPlayerId);
    btnDiscard.textContent = `Discard & Draw (${me ? me.discards_used : 0}/${me ? me.max_discards : 4} used)`;
    btnDiscard.disabled = !me || me.discards_used >= me.max_discards || !gameState.deck?.length;
    btnDiscard.addEventListener("click", discardSelected);
    actions.appendChild(btnDiscard);

    // Play button
    const btnPlay = document.createElement("button");
    btnPlay.className = "btn btn-primary";
    btnPlay.id = "btn-play";
    btnPlay.textContent = "Play selected cards";
    btnPlay.disabled = !selectedFaceUp || !selectedFaceDown;
    btnPlay.addEventListener("click", playSelected);
    actions.appendChild(btnPlay);

    // Selection hint
    const hint = document.createElement("p");
    hint.style.fontSize = ".8rem";
    hint.style.color = "#7a6a45";
    hint.style.width = "100%";
    hint.style.textAlign = "center";
    hint.textContent = selectedFaceUp
      ? `Face-up: ${selectedFaceUp} | ${selectedFaceDown ? "Face-down: " + selectedFaceDown : "Click another card for face-down"}`
      : "Click a card to set as face-up, then another for face-down";
    actions.appendChild(hint);
  }

  if (phase === "recruit" && gameState.pending_play) {
    const pending = gameState.pending_play;
    const isActor = pending.actor_id === myPlayerId;
    const isRecruiter = !isActor; // in 1v1: the other player recruits

    if (pendingArea) {
      const title = document.createElement("p");
      title.style.fontWeight = "700";
      title.style.marginBottom = "8px";
      title.textContent = isRecruiter ? "Choose a card to recruit:" : "Waiting for opponent to recruit...";
      pendingArea.appendChild(title);

      const row = document.createElement("div");
      row.style.display = "flex";
      row.style.gap = "16px";
      row.style.justifyContent = "center";

      // Face-up
      const upWrap = document.createElement("div");
      upWrap.style.textAlign = "center";
      const upCard = makeCardEl(pending.face_up, 0, {
        selectable: isRecruiter,
        onClick: isRecruiter ? () => doRecruit("face_up") : null,
      });
      upWrap.appendChild(upCard);
      upWrap.appendChild(Object.assign(document.createElement("small"), { textContent: "Face-up" }));
      row.appendChild(upWrap);

      // Face-down
      const downWrap = document.createElement("div");
      downWrap.style.textAlign = "center";
      const downCard = isRecruiter
        ? makeCardEl(pending.face_down, 0, { selectable: true, onClick: () => doRecruit("face_down") })
        : makeCardEl("?", 0, { faceDown: true });
      downWrap.appendChild(downCard);
      downWrap.appendChild(Object.assign(document.createElement("small"), { textContent: "Face-down" }));
      row.appendChild(downWrap);

      pendingArea.appendChild(row);
    }
  }
}

// ---- Card selection ----
let selectionStep = 0; // 0 = none, 1 = face-up selected

function selectHandCard(name, el) {
  const hand = document.querySelectorAll(`.hand #hand-${myPlayerId} .card, #hand-${myPlayerId} .card`);
  const allHandCards = document.querySelectorAll(`#hand-${myPlayerId} .card`);

  if (!selectedFaceUp) {
    selectedFaceUp = name;
    el.classList.add("selected");
    el.dataset.slot = "face-up";
    setStatus(`Face-up: ${name} — now click the face-down card`);
  } else if (!selectedFaceDown && name !== selectedFaceUp) {
    selectedFaceDown = name;
    el.classList.add("selected");
    el.dataset.slot = "face-down";
    setStatus(`Ready: Face-up ${selectedFaceUp} + Face-down ${selectedFaceDown}`);
  } else {
    // Reset
    selectedFaceUp = null;
    selectedFaceDown = null;
    allHandCards.forEach(c => { c.classList.remove("selected"); delete c.dataset.slot; });
    setStatus("Selection cleared — pick again");
  }
  // Re-render actions to enable/disable play button
  renderActions(gameState.phase, true, gameState.players);
}

async function discardSelected() {
  if (!selectedFaceUp) { alert("Select a card to discard first"); return; }
  try {
    const data = await api("/api/game/discard", { game_id: gameId, player_id: myPlayerId, card_name: selectedFaceUp });
    selectedFaceUp = null;
    selectedFaceDown = null;
    gameState = data.state;
    renderGameScreen();
  } catch (e) { alert(e.message); }
}

async function playSelected() {
  if (!selectedFaceUp || !selectedFaceDown) { alert("Select 2 cards first"); return; }
  const body = { game_id: gameId, player_id: myPlayerId, face_up: selectedFaceUp, face_down: selectedFaceDown };

  // Animate selected cards flying out
  document.querySelectorAll(`#hand-${myPlayerId} .card.selected`).forEach(el => {
    el.classList.add("card-fly-out");
  });
  await new Promise(r => setTimeout(r, 360));

  // FFA: target selection
  if (gameState.mode === "local_ffa") {
    const targets = gameState.players.filter(p => p.id !== myPlayerId && !p.eliminated);
    const targetName = prompt(`Choose target:\n${targets.map((t, i) => `${i+1}. ${t.name}`).join("\n")}\n(enter number)`);
    const idx = parseInt(targetName) - 1;
    if (isNaN(idx) || !targets[idx]) { alert("Invalid target"); return; }
    body.target_id = targets[idx].id;
  }

  try {
    const data = await api("/api/game/play", body);
    selectedFaceUp = null;
    selectedFaceDown = null;
    gameState = data.state;

    if (data.ai_recruited) {
      setStatus(`AI recruited: ${data.ai_recruited}`, "#4a90d9");
    }

    // In solo mode, if it's now the AI's turn, show interim state then handle AI play
    if (gameState.mode === "solo" && !gameState.result && gameState.pending_play && gameState.phase === "recruit") {
      renderGameScreen(); // show the AI's face-up + face-down for the human to recruit from
    } else {
      renderGameScreen();
    }
  } catch (e) { alert(e.message); }
}

async function doRecruit(choice) {
  if (socket) {
    socket.recruit(choice);
    return;
  }
  try {
    const data = await api("/api/game/recruit", { game_id: gameId, player_id: myPlayerId, choice });
    gameState = data.state;
    if (data.ai_played) {
      // AI has already played next turn — state shows pending play
    }
    renderGameScreen();

    // Hot-seat: show pass screen between turns in local mode
    if (gameState.mode !== "solo" && !gameState.result && gameState.phase === "play") {
      const nextPlayer = gameState.players[gameState.active_player_index];
      if (nextPlayer.id !== myPlayerId) showPassScreen(nextPlayer.name);
    }
  } catch (e) { alert(e.message); }
}

// ---- Pass screen (hot-seat) ----
function showPassScreen(nextPlayerName) {
  const overlay = document.getElementById("pass-overlay");
  const nameEl = document.getElementById("pass-player-name");
  if (overlay && nameEl) {
    nameEl.textContent = nextPlayerName;
    overlay.classList.add("visible");
  }
}

document.getElementById("btn-pass-confirm")?.addEventListener("click", () => {
  document.getElementById("pass-overlay")?.classList.remove("visible");
  myPlayerId = gameState.players[gameState.active_player_index]?.id;
  renderGameScreen();
});

// ---- Result ----
function showResult(result) {
  if (!result) return;
  const screen = document.getElementById("screen-result");
  const winnerEl = document.getElementById("result-winner");
  const reasonEl = document.getElementById("result-reason");
  if (!screen) return;

  const winner = gameState.players.find(p => p.id === result.winner_id);
  const reasons = {
    caught: "tagged their opponent!",
    three_masterminds: "collected 3 Codebreakers — unbeatable strategy!",
    three_show_offs: "opponent collected 3 Daredevils!",
    out_of_cards: "closest to catching when cards ran out!",
  };

  if (winnerEl) winnerEl.textContent = winner ? `${winner.name} wins!` : "Game over!";
  if (reasonEl) reasonEl.textContent = reasons[result.reason] || result.reason;

  show("screen-result");

  // Board catch flash
  if (result.reason === "caught") {
    const boardContainer = document.getElementById("board-container");
    boardCatchFlash(boardContainer);
  }

  // Result box pop animation (retriggered each time)
  const box = document.getElementById("result-box");
  if (box) {
    box.classList.remove("result-pop-anim");
    void box.offsetWidth;
    box.classList.add("result-pop-anim");
  }

  // Confetti only if there's a real winner (not a draw or timer timeout loss)
  if (result.winner_id) spawnConfetti();
}

function spawnConfetti() {
  const colors = ["#2d7a45", "#f5c842", "#4a90d9", "#e05252", "#9b59b6", "#ff8c00", "#00bcd4"];
  for (let i = 0; i < 90; i++) {
    const p = document.createElement("div");
    p.className = "confetti-particle";
    const drift = ((Math.random() - 0.5) * 55).toFixed(1);
    const startY = (-8 - Math.random() * 28).toFixed(1);
    p.style.cssText = `
      left:${(Math.random() * 100).toFixed(1)}vw;
      background:${colors[Math.floor(Math.random() * colors.length)]};
      --start-y:${startY}vh;
      --drift:${drift}vw;
      --fall-dur:${(1.8 + Math.random() * 1.6).toFixed(2)}s;
      --fall-delay:${(Math.random() * 0.9).toFixed(2)}s;
    `;
    document.body.appendChild(p);
    setTimeout(() => p.remove(), 3800);
  }
}

document.getElementById("btn-play-again")?.addEventListener("click", () => {
  gameId = null; gameState = null; myPlayerId = null;
  selectedFaceUp = null; selectedFaceDown = null;
  lastRenderedActivePlayerId = null;
  timerReset();
  show("screen-menu");
});

// ============================================================
// AUTH MODAL — functions exposed globally for onclick handlers
// ============================================================

window.openAuthModal = function () {
  document.getElementById("auth-modal")?.classList.remove("hidden");
  window.switchTab("login");
};

window.closeAuthModal = function () {
  document.getElementById("auth-modal")?.classList.add("hidden");
};

window.closeAuthOnBackdrop = function (e) {
  if (e.target?.id === "auth-modal") window.closeAuthModal();
};

window.switchTab = function (tab) {
  document.getElementById("form-login")?.classList.toggle("hidden", tab !== "login");
  document.getElementById("form-register")?.classList.toggle("hidden", tab !== "register");
  document.getElementById("tab-login")?.classList.toggle("active", tab === "login");
  document.getElementById("tab-register")?.classList.toggle("active", tab === "register");
};

window.doLogin = async function () {
  const username = document.getElementById("login-username")?.value.trim();
  const password = document.getElementById("login-password")?.value;
  const errEl    = document.getElementById("login-error");
  errEl?.classList.add("hidden");
  if (!username || !password) {
    if (errEl) { errEl.textContent = "Enter username and password"; errEl.classList.remove("hidden"); }
    return;
  }
  try {
    const res  = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Login failed");
    _saveAuth(data.access_token, data.username);
    updateAuthUI();
    window.closeAuthModal();
  } catch (e) {
    if (errEl) { errEl.textContent = e.message; errEl.classList.remove("hidden"); }
  }
};

window.doRegister = async function () {
  const username = document.getElementById("reg-username")?.value.trim();
  const email    = document.getElementById("reg-email")?.value.trim();
  const password = document.getElementById("reg-password")?.value;
  const errEl    = document.getElementById("reg-error");
  errEl?.classList.add("hidden");
  if (!username || !email || !password) {
    if (errEl) { errEl.textContent = "All fields required"; errEl.classList.remove("hidden"); }
    return;
  }
  try {
    const res  = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Registration failed");
    _saveAuth(data.access_token, data.username);
    updateAuthUI();
    window.closeAuthModal();
  } catch (e) {
    if (errEl) { errEl.textContent = e.message; errEl.classList.remove("hidden"); }
  }
};

window.doLogout = function () {
  _clearAuth();
  updateAuthUI();
};

// ============================================================
// LEADERBOARD MODAL
// ============================================================

window.showLeaderboard = async function () {
  document.getElementById("leaderboard-modal")?.classList.remove("hidden");
  const listEl = document.getElementById("leaderboard-list");
  if (!listEl) return;
  listEl.innerHTML = `<p style="color:#aaa;text-align:center;padding:20px;">Loading…</p>`;
  try {
    const res  = await fetch("/api/auth/leaderboard");
    const data = await res.json();
    if (!res.ok) throw new Error("Failed to load");
    const rows = data.leaderboard || [];
    if (!rows.length) {
      listEl.innerHTML = `<p style="color:#aaa;text-align:center;padding:20px;">No entries yet — play some games!</p>`;
      return;
    }
    const medals = ["🥇", "🥈", "🥉"];
    const medalCls = ["gold", "silver", "bronze"];
    listEl.innerHTML = rows.map((r, i) => `
      <div class="leaderboard-row">
        <span class="lb-rank ${medalCls[i] || ""}">${medals[i] || `#${i + 1}`}</span>
        <span class="lb-name">${r.username}</span>
        <span class="lb-wins">${r.wins}W / ${r.games_played}G</span>
        <span class="lb-rate">${r.win_rate}%</span>
      </div>`).join("");
  } catch (e) {
    if (listEl) listEl.innerHTML = `<p style="color:#e05252;text-align:center;padding:20px;">Error: ${e.message}</p>`;
  }
};

window.closeLeaderboard = function () {
  document.getElementById("leaderboard-modal")?.classList.add("hidden");
};

window.closeLeaderboardOnBackdrop = function (e) {
  if (e.target?.id === "leaderboard-modal") window.closeLeaderboard();
};

// ============================================================
// IN-GAME CHAT (online mode)
// ============================================================

window.sendChatAll = function () {
  const input = document.getElementById("ingame-chat-text");
  const text  = input?.value.trim();
  if (!text || !socket) return;
  socket.send("chat_all", { text });
  if (input) input.value = "";
};

window.sendReaction = function (reaction) {
  socket?.send("reaction", { reaction });
};

// Also allow Enter key in chat input
document.getElementById("ingame-chat-text")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") window.sendChatAll();
});

// ---- Init ----
updateAuthUI();
show("screen-menu");
