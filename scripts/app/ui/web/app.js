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

async function appendResponseDetail() {
  if (!window.pywebview?.api) return;
  const text = await window.pywebview.api.get_response_detail();
  if (!text) return;
  const panel = document.createElement('details');
  const title = document.createElement('summary');
  title.textContent = '상세 보기';
  const body = document.createElement('div');
  body.style.whiteSpace = 'pre-wrap';
  body.textContent = text;
  panel.append(title, body);
  chatStream.append(panel);
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
    await appendResponseDetail();
    
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

async function showAppPermissions() {
  const dialog = document.getElementById('app-permissions');
  const list = document.getElementById('app-permission-list');
  if (!dialog.open) dialog.showModal();
  list.replaceChildren();
  try {
    const entries = await window.pywebview.api.get_app_permissions();
    if (!entries.length) list.textContent = '저장된 실행 허용 앱이 없습니다.';
    for (const entry of entries) {
      const row = document.createElement('p');
      const label = document.createElement('span');
      label.textContent = `${entry.name} — ${entry.path} (${entry.status}) `;
      const button = document.createElement('button');
      button.textContent = '허용 취소';
      button.onclick = async () => {
        button.disabled = true;
        try {
          const message = await window.pywebview.api.revoke_app_permission(entry.id);
          appendMessage('JARVIS', message, false);
          await showAppPermissions();
        } catch (error) {
          button.disabled = false;
          label.textContent = `허용 취소 실패: ${error}`;
        }
      };
      row.append(label, button);
      list.append(row);
    }
  } catch (error) {
    list.textContent = `허용 목록을 읽지 못했습니다: ${error}`;
  }
}

function showHelp() {
  appendMessage('JARVIS', '사용 가능한 프로토콜: /help(도움말), /clear(문맥 초기화), /budget(비용 현황), /open_app 앱이름(앱 실행), /apps(실행 허용 목록), /apps revoke ID(허용 취소), /bye(종료)', false);
}

// Voice Event Handlers called from Python bridge
window.onJarvisWake = function() {
  const lastVoice = document.getElementById('last-voice-val');
  if (lastVoice) lastVoice.textContent = '호출어 감지됨...';

  setReactorState('listening');
  startWaveAnimation();
};

window.onJarvisVoiceInput = function(text) {
  const lastVoice = document.getElementById('last-voice-val');
  if (lastVoice) lastVoice.textContent = text;

  appendMessage('VOICE', text, true);
  setReactorState('thinking');
};

window.onJarvisVoiceOutput = function(text) {
  appendMessage('JARVIS', text, false);
  appendResponseDetail().catch(console.warn);
  setReactorState('speaking');
};

window.onJarvisStateChange = function(state) {
  setReactorState(state);
  if (state === 'listening' || state === 'speaking') {
    startWaveAnimation();
  } else if (state === 'idle') {
    stopWaveAnimation();
  }
};

window.onMicStateChanged = function(isActive) {
  // 1. Top status bar badge
  const headerBadge = document.getElementById('mic-status-val');
  if (headerBadge) {
    if (isActive) {
      headerBadge.textContent = '● LISTENING';
      headerBadge.className = 'metric-val text-green';
    } else {
      headerBadge.textContent = '○ MUTED';
      headerBadge.className = 'metric-val accent-gold';
    }
  }

  // 2. Left Protocol Controls panel button
  const panelMicText = document.getElementById('panel-mic-text');
  const panelMicBtn = document.getElementById('panel-mic-btn');
  const panelMicIcon = document.getElementById('panel-mic-icon');
  if (panelMicText && panelMicBtn) {
    if (isActive) {
      panelMicText.textContent = 'VOICE MIC: LISTENING';
      panelMicText.style.color = 'var(--green-ok)';
      panelMicBtn.style.borderColor = 'rgba(0, 255, 136, 0.6)';
      panelMicBtn.style.boxShadow = '0 0 12px rgba(0, 255, 136, 0.2)';
      if (panelMicIcon) panelMicIcon.textContent = '🎙️';
    } else {
      panelMicText.textContent = 'VOICE MIC: MUTED';
      panelMicText.style.color = 'var(--gold-neon)';
      panelMicBtn.style.borderColor = 'rgba(255, 183, 0, 0.6)';
      panelMicBtn.style.boxShadow = '0 0 12px rgba(255, 183, 0, 0.2)';
      if (panelMicIcon) panelMicIcon.textContent = '🔇';
    }
  }

  // 3. Telemetry Voice Sensor
  const sensorVal = document.getElementById('voice-sensor-val');
  if (sensorVal) {
    sensorVal.textContent = isActive ? 'ONLINE' : 'MUTED';
    sensorVal.className = isActive ? 'telemetry-val text-green' : 'telemetry-val accent-gold';
  }
};

async function toggleMic() {
  if (window.pywebview && window.pywebview.api) {
    const res = await window.pywebview.api.toggle_mic();
    window.onMicStateChanged(!res.mic_muted);
  }
}

window.addEventListener('DOMContentLoaded', async () => {
  chatInput.focus();
  if (window.pywebview && window.pywebview.api) {
    try {
      const status = await window.pywebview.api.get_status();
      if (!status.voice_enabled) {
        window.onMicStateChanged(false);
      }
    } catch (e) {
      console.warn('Status check deferred', e);
    }
  }
});
