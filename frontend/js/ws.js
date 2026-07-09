/* ============================================================
   ws.js — WebSocket client for online mode
   ============================================================ */

export class GameSocket {
  constructor(onMessage, onClose) {
    this._onMessage = onMessage;
    this._onClose = onClose;
    this._ws = null;
    this.token = null;
    this.playerName = null;
  }

  connect(playerName) {
    return new Promise((resolve, reject) => {
      const proto = location.protocol === "https:" ? "wss:" : "ws:";
      const url = `${proto}//${location.host}/ws`;
      this._ws = new WebSocket(url);

      const timeout = setTimeout(() => {
        reject(new Error("Connection timeout"));
        this._ws.close();
      }, 8000);

      this._ws.onopen = () => {
        this._ws.send(JSON.stringify({ type: "auth", player_name: playerName }));
      };

      this._ws.onmessage = (event) => {
        let msg;
        try { msg = JSON.parse(event.data); } catch { return; }

        if (!this.token) {
          if (msg.type === "auth_ok") {
            clearTimeout(timeout);
            this.token = msg.token;
            this.playerName = msg.player_name;
            this._ws.onmessage = (e) => {
              let m; try { m = JSON.parse(e.data); } catch { return; }
              this._onMessage(m);
            };
            resolve(msg);
          } else if (["auth_timeout", "rate_limited", "error"].includes(msg.type)) {
            clearTimeout(timeout);
            reject(new Error(msg.message || "Could not connect"));
            this._ws.close();
          }
        } else {
          this._onMessage(msg);
        }
      };

      this._ws.onclose = () => {
        clearTimeout(timeout);
        this._onClose?.();
      };

      this._ws.onerror = () => {
        clearTimeout(timeout);
        reject(new Error("WebSocket error — could not connect"));
      };
    });
  }

  send(type, payload = {}) {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
      console.warn("WebSocket not connected");
      return;
    }
    this._ws.send(JSON.stringify({ type, token: this.token, ...payload }));
  }

  createRoom(mode, roomName = "", roomPassword = "") {
    this.send("create_room", { mode, room_name: roomName, room_password: roomPassword });
  }
  joinRoom(roomId, roomPassword = "") {
    this.send("join_room", { room_id: roomId, room_password: roomPassword });
  }
  rejoinRoom(roomId) { this.send("rejoin_room", { room_id: roomId }); }
  leaveRoom() { this.send("leave_room"); }
  listRooms() { this.send("list_rooms"); }
  startGame() { this.send("start_game"); }
  discard(cardName) { this.send("discard", { card_name: cardName }); }
  playCards(faceUp, faceDown, targetId = null) {
    this.send("play_cards", { face_up: faceUp, face_down: faceDown, target_id: targetId });
  }
  recruit(choice) { this.send("recruit", { choice }); }
  ping() { this.send("ping"); }

  disconnect() {
    this._ws?.close();
    this._ws = null;
    this.token = null;
  }

  get connected() { return this._ws?.readyState === WebSocket.OPEN; }
}
