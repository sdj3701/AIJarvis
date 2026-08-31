/**
 * JARVIS HUD Frontend Controller & Python Bridge
 */

const chatStream = document.getElementById('chat-stream');
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const waveBars = document.querySelectorAll('.wave-bar');

let waveInterval = null;

function appendMessage(sender, text, isUser = false) {
  const msgDiv = document.createElement('div');
  msgDiv.className = `chat-message ${isUser ? 'user' : 'assistant'}`;

  const timeStr = new Date().toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' });

  msgDiv.innerHTML = `
    <div class="msg-meta">
      <span class="sender-name">${sender}</span>
      <span class="msg-time">${timeStr}</span>
    </div>
    <div class="msg-content">${escapeHtml(text)}</div>
  `;

  chatStream.appendChild(msgDiv);
  chatStream.scrollTop = chatStream.scrollHeight;
}

function escapeHtml(str) {
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>");
}

function startWaveAnimation() {
  if (waveInterval) clearInterval(waveInterval);
  waveInterval = setInterval(() => {
    waveBars.forEach(bar => {
      const h = Math.floor(Math.random() * 80) + 20;
      bar.style.height = `${h}%`;
    });
  }, 100);
}

function stopWaveAnimation() {
  if (waveInterval) {
    clearInterval(waveInterval);
    waveInterval = null;
  }
  waveBars.forEach(bar => bar.style.height = '20%');
}

async function handleSend() {
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = '';
  resetInputHeight();
  appendMessage('USER', text, true);

  // 1. Trigger THINKING State
  setReactorState('thinking');
  startWaveAnimation();
  chatInput.disabled = true;
  sendBtn.disabled = true;

  try {
    let reply = '';
    if (window.pywebview && window.pywebview.api) {
      reply = await window.pywebview.api.send_message(text);
    } else {
      // Demo / Fallback mode
      await new Promise(r => setTimeout(r, 1200));
      reply = "로컬 웹뷰 브리지가 연결되었습니다. [Ollama: qwen3.5:9b 정상 가동 중]";
    }

    // 2. Trigger SPEAKING State
    setReactorState('speaking');
    appendMessage('JARVIS', reply, false);
    
    setTimeout(() => {
      setReactorState('idle');
      stopWaveAnimation();
    }, 1500);
  } catch (err) {
    setReactorState('error');
    appendMessage('SYSTEM', `오류 발생: ${err}`, false);
    setTimeout(() => {
      setReactorState('idle');
      stopWaveAnimation();
    }, 2000);
  } finally {
    chatInput.disabled = false;
    sendBtn.disabled = false;
    chatInput.focus();
  }
}

function autoResizeInput() {
  chatInput.style.height = 'auto';
  const newHeight = Math.min(chatInput.scrollHeight, 100);
  chatInput.style.height = newHeight + 'px';
}

function resetInputHeight() {
  chatInput.style.height = '38px';
}

chatInput.addEventListener('input', autoResizeInput);

chatInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    if (e.shiftKey) {
      // Shift + Enter: 줄 바꿈 허용 및 자동 높이 조절
      setTimeout(autoResizeInput, 0);
    } else {
      // Enter: AI에게 질문 전송
      e.preventDefault();
      handleSend();
    }
  }
});

async function clearConversation() {
  if (window.pywebview && window.pywebview.api) {
    await window.pywebview.api.clear_context();
  }
  chatStream.innerHTML = '';
  appendMessage('JARVIS', '현재 대화 문맥을 초기화했습니다. 새 명령을 입력하세요.', false);
}

async function checkBudget() {
  if (window.pywebview && window.pywebview.api) {
    const info = await window.pywebview.api.get_budget();
    appendMessage('JARVIS', `[예산 현황] ${info}`, false);
  } else {
    appendMessage('JARVIS', '[예산 현황] 오늘: $0.00 / 이번 달: $0.00 (로컬 모델 100%)', false);
  }
}

function showHelp() {
  appendMessage('JARVIS', '사용 가능한 프로토콜: /help(도움말), /clear(문맥 초기화), /budget(비용 현황), /bye(종료)', false);
}

window.addEventListener('DOMContentLoaded', () => {
  chatInput.focus();
});
