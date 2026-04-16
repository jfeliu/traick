"""
Development-only endpoints for testing without WhatsApp.

Enabled only when DEV_MODE=true in .env.
Visit /dev/chat in your browser to send messages and see AI replies.
"""

import logging
import time

from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from traick.ai.responder import generate_reply
from traick.db.repository import (
    get_active_projects,
    get_recent_messages,
    save_raw_message,
    save_reply_message,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dev")

_CHAT_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Traick — Dev Chat</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #ece5dd; min-height: 100vh; display: flex; flex-direction: column; align-items: center; padding: 24px 16px; }
  .card { background: white; border-radius: 12px; box-shadow: 0 2px 12px rgba(0,0,0,.12); width: 100%; max-width: 560px; display: flex; flex-direction: column; overflow: hidden; }
  .header { background: #075e54; color: white; padding: 14px 18px; display: flex; align-items: center; gap: 12px; }
  .avatar { width: 38px; height: 38px; border-radius: 50%; background: #25d366; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; }
  .header-info { flex: 1; }
  .header-name { font-weight: 600; font-size: .95rem; }
  .header-sub { font-size: .75rem; opacity: .8; }
  .phone-btn { background: rgba(255,255,255,.15); border: none; color: white; border-radius: 6px; padding: 4px 10px; font-size: .75rem; cursor: pointer; }
  .phone-btn:hover { background: rgba(255,255,255,.25); }
  #chat { flex: 1; padding: 16px; min-height: 340px; max-height: 460px; overflow-y: auto; background: #ece5dd url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='200' height='200' opacity='.03'%3E%3Ctext y='100' font-size='80'%3E💬%3C/text%3E%3C/svg%3E"); display: flex; flex-direction: column; gap: 6px; }
  .msg { display: flex; }
  .msg.out { justify-content: flex-end; }
  .bubble { max-width: 78%; padding: 8px 12px 6px; border-radius: 8px; font-size: .9rem; line-height: 1.4; word-wrap: break-word; white-space: pre-wrap; position: relative; }
  .msg.in .bubble { background: white; border-top-left-radius: 2px; }
  .msg.out .bubble { background: #dcf8c6; border-top-right-radius: 2px; }
  .time { font-size: .68rem; color: #999; margin-top: 3px; text-align: right; }
  .typing { display: none; align-items: center; gap: 4px; padding: 10px 12px; background: white; border-radius: 8px; border-top-left-radius: 2px; width: fit-content; }
  .typing span { width: 7px; height: 7px; background: #aaa; border-radius: 50%; animation: bounce .9s infinite; }
  .typing span:nth-child(2) { animation-delay: .15s; }
  .typing span:nth-child(3) { animation-delay: .3s; }
  @keyframes bounce { 0%,60%,100% { transform: translateY(0); } 30% { transform: translateY(-5px); } }
  .form-row { display: flex; gap: 8px; padding: 10px 12px; background: #f0f0f0; border-top: 1px solid #ddd; }
  #input { flex: 1; padding: 10px 14px; border: none; border-radius: 20px; outline: none; font-size: .9rem; background: white; }
  .send-btn { width: 42px; height: 42px; border-radius: 50%; background: #075e54; color: white; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
  .send-btn:disabled { background: #aaa; cursor: default; }
  .send-btn svg { width: 20px; height: 20px; fill: white; }
</style>
</head>
<body>
<div class="card">
  <div class="header">
    <div class="avatar">🤖</div>
    <div class="header-info">
      <div class="header-name">Traick</div>
      <div class="header-sub" id="phone-display"></div>
    </div>
    <button class="phone-btn" onclick="changePhone()">Change number</button>
  </div>
  <div id="chat">
    <div id="typing" class="msg in"><div class="typing"><span></span><span></span><span></span></div></div>
  </div>
  <form class="form-row" id="form">
    <input id="input" type="text" placeholder="Type a message…" autocomplete="off" />
    <button class="send-btn" type="submit" id="send-btn" title="Send">
      <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
  </form>
</div>
<script>
const chat = document.getElementById('chat');
const input = document.getElementById('input');
const btn = document.getElementById('send-btn');
const typing = document.getElementById('typing');
const phoneDisplay = document.getElementById('phone-display');

let phone = localStorage.getItem('devPhone') || 'dev-test-user';
phoneDisplay.textContent = phone;

function changePhone() {
  const p = prompt('Phone / identifier for this test session:', phone);
  if (p && p.trim()) {
    phone = p.trim();
    localStorage.setItem('devPhone', phone);
    phoneDisplay.textContent = phone;
  }
}

function now() {
  return new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'});
}

function addMessage(text, dir) {
  typing.before(Object.assign(document.createElement('div'), {
    className: `msg ${dir}`,
    innerHTML: `<div class="bubble">${text.replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\\n/g,'<br>')}<div class="time">${now()}</div></div>`
  }));
  chat.scrollTop = chat.scrollHeight;
}

document.getElementById('form').addEventListener('submit', async e => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  btn.disabled = true;
  addMessage(text, 'out');
  typing.style.display = 'flex';
  chat.scrollTop = chat.scrollHeight;
  try {
    const res = await fetch('/dev/message', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({phone, message: text})
    });
    const data = await res.json();
    typing.style.display = 'none';
    addMessage(data.reply || '(no reply)', 'in');
  } catch (err) {
    typing.style.display = 'none';
    addMessage('Error: ' + err, 'in');
  } finally {
    btn.disabled = false;
    input.focus();
  }
});

input.focus();
</script>
</body>
</html>"""


class DevMessage(BaseModel):
    phone: str = "dev-test-user"
    message: str


@router.get("/chat", response_class=HTMLResponse)
async def dev_chat():
    """Browser-based chat UI for local testing."""
    return _CHAT_HTML


@router.post("/message")
async def dev_message(body: DevMessage):
    """Simulate an inbound WhatsApp message and return the AI reply directly."""
    timestamp = int(time.time())
    await save_raw_message(
        wa_id=f"dev-{timestamp}",
        from_number=body.phone,
        body=body.message,
        timestamp=timestamp,
    )
    projects = await get_active_projects(body.phone)
    recent = await get_recent_messages(body.phone, limit=10)
    reply = await generate_reply(
        incoming=body.message,
        from_number=body.phone,
        projects=projects,
        recent_messages=recent,
    )
    if reply:
        await save_reply_message(from_number=body.phone, body=reply)
    return {"reply": reply}
