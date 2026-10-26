/* 内嵌终端：Bridge 的 PTY 会话，xterm.js 只做渲染与按键 */
const TERMINAL = {
  dock: null, term: null, fit: null, source: null, session: null,
  claude: null, cwd: null, opened: false, busy: false,
  inputBuffer: '', inputTimer: 0, resizeTimer: 0, retries: 0,
};

const TERMINAL_MAX_RETRIES = 3;
const TERMINAL_THEME = {
  background: '#0b0f14', foreground: '#d7e2ee', cursor: '#e2e8f0',
  selectionBackground: 'rgba(56,189,248,.35)', black: '#1f2937', red: '#f87171',
  green: '#4ade80', yellow: '#facc15', blue: '#60a5fa', magenta: '#c084fc',
  cyan: '#22d3ee', white: '#e5e7eb',
};

function terminalB64FromBytes(bytes){
  let binary = '';
  for(let i = 0; i < bytes.length; i += 0x8000){
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function terminalBytesFromB64(value){
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for(let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function terminalFetchJson(url, body){
  const options = body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
  };
  const response = await fetch(url, options);
  let payload = null;
  try{ payload = await response.json(); }catch(error){ payload = null; }
  if(!response.ok || !payload || payload.ok === false){
    throw new Error((payload && payload.error) || `请求失败（${response.status}）`);
  }
  return payload;
}

function terminalToolbarButton(){
  return '<button id="pipelineTerminal" title="内嵌终端：可在其中启动 Claude 会话，通过 forgeworks MCP 操作项目">终端</button>';
}

function terminalEnsureDock(){
  if(TERMINAL.dock) return TERMINAL.dock;
  const main = document.querySelector('.main');
  if(!main) return null;
  const dock = document.createElement('section');
  dock.id = 'fwTerminalDock';
  dock.className = 'hide';
  dock.innerHTML = `<header>
    <span class="fw-term-dot" data-state="idle"></span><b>终端</b>
    <span class="fw-term-cwd"></span>
    <button id="fwTermClaude" class="sm" disabled>启动 Claude</button>
    <button id="fwTermClose" class="sm">关闭</button>
  </header><div class="fw-term-body"></div>`;
  main.appendChild(dock);
  dock.querySelector('#fwTermClaude').onclick = () => terminalStartClaude();
  dock.querySelector('#fwTermClose').onclick = () => terminalClose();
  TERMINAL.dock = dock;
  return dock;
}

function terminalSetState(state, cwd){
  if(!TERMINAL.dock) return;
  const dot = TERMINAL.dock.querySelector('.fw-term-dot');
  if(dot) dot.dataset.state = state;
  if(cwd !== undefined){
    const label = TERMINAL.dock.querySelector('.fw-term-cwd');
    if(label) label.textContent = cwd || '';
  }
}

function terminalShowNotice(message){
  const dock = terminalEnsureDock();
  if(!dock) return;
  const body = dock.querySelector('.fw-term-body');
  if(body) body.innerHTML = `<div class="fw-term-notice">${terminalEscape(message)}</div>`;
}

function terminalEscape(text){
  return String(text == null ? '' : text)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function terminalNotify(message){
  if(typeof toast === 'function') toast(message);
}

function terminalSetClaudeButton(info){
  const button = TERMINAL.dock && TERMINAL.dock.querySelector('#fwTermClaude');
  if(!button) return;
  button.disabled = !(info && info.available);
  button.title = (info && info.available) ? '在当前目录启动 Claude 会话（已注入 forgeworks MCP）'
    : ((info && info.reason) || '未找到 claude 命令');
}

async function terminalOpen(){
  if(TERMINAL.opened){
    if(TERMINAL.busy) return;
    terminalSetBusy(true);
    try{
      if(TERMINAL.term) TERMINAL.term.reset();
      await terminalStartSession();
    }catch(error){
      terminalSetState('error');
      terminalShowNotice(error.message || '无法启动终端');
    }finally{
      terminalSetBusy(false);
    }
    return;
  }
  const dock = terminalEnsureDock();
  if(!dock) return;
  dock.classList.remove('hide');
  TERMINAL.opened = true;
  TERMINAL.retries = 0;
  terminalSetState('connecting', '');
  terminalShowNotice('正在连接 Bridge…');
  terminalSetBusy(true);
  try{
    await terminalStartSession();
  }catch(error){
    terminalSetState('error');
    terminalShowNotice(error.message || '无法启动终端');
  }finally{
    terminalSetBusy(false);
  }
}

function terminalSetBusy(busy){
  TERMINAL.busy = busy;
  const dock = TERMINAL.dock;
  if(!dock) return;
  const button = dock.querySelector('#fwTermClaude');
  if(button && busy) button.disabled = true;
}

async function terminalStartSession(){
  const status = await terminalFetchJson('/api/terminal/status');
  TERMINAL.claude = status.claude || {};
  terminalSetClaudeButton(TERMINAL.claude);
  if(!status.available) throw new Error(status.reason || '当前平台不支持内嵌终端');
  if(!status.project) throw new Error('尚未绑定项目：请先在「同步」页新建或打开项目');
  if(!TERMINAL.term) terminalMountTerm();
  const dimensions = (TERMINAL.fit && TERMINAL.fit.proposeDimensions()) || {cols: 100, rows: 30};
  const session = await terminalFetchJson('/api/terminal/start',
    {cols: dimensions.cols, rows: dimensions.rows});
  TERMINAL.session = {id: session.id, token: session.token};
  TERMINAL.cwd = session.cwd;
  terminalSetState('connecting', session.cwd);
  terminalConnectStream();
  if(TERMINAL.term) TERMINAL.term.focus();
}

function terminalMountTerm(){
  const dock = terminalEnsureDock();
  const body = dock && dock.querySelector('.fw-term-body');
  if(!body || typeof Terminal !== 'function') throw new Error('xterm.js 未加载');
  body.innerHTML = '';
  const term = new Terminal({
    theme: TERMINAL_THEME,
    fontFamily: '"SFMono-Regular", ui-monospace, Menlo, Consolas, monospace',
    fontSize: 13,
    lineHeight: 1.2,
    cursorBlink: true,
    scrollback: 5000,
    convertEol: false,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.open(body);
  fit.fit();
  term.onData(data => terminalQueueInput(data));
  term.onResize(size => terminalQueueResize(size.cols, size.rows));
  TERMINAL.term = term;
  TERMINAL.fit = fit;
  if(!TERMINAL.resizeObserver && typeof ResizeObserver === 'function'){
    TERMINAL.resizeObserver = new ResizeObserver(() => terminalQueueResize());
    TERMINAL.resizeObserver.observe(body);
  }
}

function terminalConnectStream(){
  terminalCloseStream();
  const session = TERMINAL.session;
  if(!session || !TERMINAL.term) return;
  const url = `/api/terminal/stream/${encodeURIComponent(session.id)}?token=${encodeURIComponent(session.token)}`;
  const source = new EventSource(url);
  TERMINAL.source = source;
  source.addEventListener('ready', event => {
    const payload = terminalParseEvent(event);
    if(payload.reset) TERMINAL.term.reset();
    TERMINAL.retries = 0;
    terminalSetState('live', TERMINAL.cwd);
    terminalQueueResize();
  });
  source.addEventListener('output', event => {
    const payload = terminalParseEvent(event);
    if(payload.b64) TERMINAL.term.write(terminalBytesFromB64(payload.b64));
  });
  source.addEventListener('exit', event => {
    const payload = terminalParseEvent(event);
    terminalSetState('exited');
    terminalCloseStream(true);
    TERMINAL.session = null;
    TERMINAL.term.write(`\r\n\x1b[90m[终端已退出${payload.code == null ? '' : '，退出码 ' + payload.code}]\x1b[0m\r\n`);
  });
  source.onerror = () => {
    if(source !== TERMINAL.source) return;
    TERMINAL.retries += 1;
    if(TERMINAL.retries > TERMINAL_MAX_RETRIES){
      terminalCloseStream(true);
      TERMINAL.session = null;
      terminalSetState('error');
      terminalShowNotice('终端连接已断开（Bridge 可能重启了）。请关闭后重新打开终端。');
    }else{
      terminalSetState('connecting');
    }
  };
}

function terminalParseEvent(event){
  try{ return JSON.parse(event.data || '{}'); }catch(error){ return {}; }
}

function terminalCloseStream(keepSession){
  if(TERMINAL.source){
    TERMINAL.source.close();
    TERMINAL.source = null;
  }
  if(!keepSession) TERMINAL.retries = 0;
}

function terminalQueueInput(data){
  if(!data || !TERMINAL.session) return;
  TERMINAL.inputBuffer += data;
  if(TERMINAL.inputTimer) return;
  TERMINAL.inputTimer = setTimeout(terminalFlushInput, 8);
}

async function terminalFlushInput(){
  TERMINAL.inputTimer = 0;
  const session = TERMINAL.session;
  const text = TERMINAL.inputBuffer;
  TERMINAL.inputBuffer = '';
  if(!session || !text) return;
  try{
    await terminalFetchJson('/api/terminal/input', {
      sessionId: session.id, token: session.token,
      data: terminalB64FromBytes(new TextEncoder().encode(text)),
    });
  }catch(error){
    terminalNotify('终端输入发送失败：' + error.message);
  }
}

function terminalQueueResize(){
  if(!TERMINAL.term || !TERMINAL.session) return;
  clearTimeout(TERMINAL.resizeTimer);
  TERMINAL.resizeTimer = setTimeout(terminalFlushResize, 120);
}

async function terminalFlushResize(){
  const session = TERMINAL.session;
  if(!TERMINAL.term || !session) return;
  if(TERMINAL.fit) TERMINAL.fit.fit();
  const {cols, rows} = TERMINAL.term;
  try{
    await terminalFetchJson('/api/terminal/resize', {sessionId: session.id, token: session.token, cols, rows});
  }catch(error){ /* 尺寸同步失败不影响输入 */ }
}

function terminalSend(text){
  const data = String(text || '');
  if(!data) return;
  terminalQueueInput(data);
  if(TERMINAL.term) TERMINAL.term.focus();
}

function terminalStartClaude(){
  if(!TERMINAL.session){
    terminalNotify('请先打开终端');
    return;
  }
  const info = TERMINAL.claude;
  if(!info || !info.available || !info.command){
    terminalNotify((info && info.reason) || '未找到 claude 命令');
    return;
  }
  terminalSend(info.command + '\r');
}

async function terminalClose(){
  terminalCloseStream();
  const session = TERMINAL.session;
  TERMINAL.session = null;
  TERMINAL.inputBuffer = '';
  clearTimeout(TERMINAL.inputTimer);
  clearTimeout(TERMINAL.resizeTimer);
  if(TERMINAL.term){
    TERMINAL.term.dispose();
    TERMINAL.term = null;
    TERMINAL.fit = null;
  }
  if(TERMINAL.resizeObserver){
    TERMINAL.resizeObserver.disconnect();
    TERMINAL.resizeObserver = null;
  }
  if(TERMINAL.dock){
    TERMINAL.dock.classList.add('hide');
    const body = TERMINAL.dock.querySelector('.fw-term-body');
    if(body) body.innerHTML = '';
  }
  TERMINAL.opened = false;
  terminalSetState('idle');
  if(session){
    try{
      await terminalFetchJson('/api/terminal/stop', {sessionId: session.id, token: session.token});
    }catch(error){ /* Bridge 已退出时无需再回收 */ }
  }
}

function terminalToggle(){
  if(TERMINAL.opened && TERMINAL.session) terminalClose();
  else terminalOpen();
}

function terminalDispose(){
  if(TERMINAL.opened) terminalClose();
  if(TERMINAL.dock){
    TERMINAL.dock.remove();
    TERMINAL.dock = null;
  }
}

function terminalOnViewChange(next){
  if(next !== 'pipeline' && TERMINAL.opened) terminalClose();
}

async function terminalOnPipelineRender(){
  if(!TERMINAL.opened || !TERMINAL.session) return;
  try{
    const status = await terminalFetchJson('/api/terminal/status');
    if(status.project && TERMINAL.cwd && status.project !== TERMINAL.cwd){
      await terminalClose();
      terminalNotify('项目已切换，终端已关闭');
    }else if(status.claude){
      TERMINAL.claude = status.claude;
      terminalSetClaudeButton(status.claude);
    }
  }catch(error){ /* 状态查询失败时保持终端现状 */ }
}

window.addEventListener('pagehide', () => {
  const session = TERMINAL.session;
  if(!session || !navigator.sendBeacon) return;
  const body = new Blob([JSON.stringify({sessionId: session.id, token: session.token})],
    {type: 'application/json'});
  navigator.sendBeacon('/api/terminal/stop', body);
});
