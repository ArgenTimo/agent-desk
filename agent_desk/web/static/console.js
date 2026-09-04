/* The console's browser half, and all of it.
 *
 * Four jobs, none of which needs a framework: keep the page in step with the server, switch
 * between chats, carry a card into the middle when somebody drags one there, and say plainly when
 * the connection has gone quiet. Everything else is server-rendered — htmx, when it is present,
 * only removes the page reload (docs/adr/0003).
 */

const poll = window.POLL_SECONDS || 2;
const asof = document.getElementById('asof');
const state = document.getElementById('stream-state');
const out = document.getElementById('out');
const pins = document.getElementById('pins');
let lastChecked = 0;

if (!window.htmx) document.getElementById('no-htmx').hidden = false;

/* --- posting without htmx ---------------------------------------------------------------------- */
// htmx is vendored, not fetched, so it is sometimes not there — and the two things this page does
// constantly are a form post and a swap. Without this, asking a question navigates away and comes
// back, which is a page reload in the middle of the one interaction that is supposed to cost
// nothing (docs/04-threads-and-blocks.md). With htmx present this does nothing at all: htmx has
// already handled the submit, and two posts would ask the same question twice.
document.addEventListener('submit', async (event) => {
  const form = event.target;
  if (window.htmx || !form.hasAttribute('hx-post')) return;
  const selector = form.getAttribute('hx-target');
  const into = selector === 'closest .tabs' ? form.closest('.tabs') : document.querySelector(selector);
  if (!into) return;

  event.preventDefault();
  const body = new URLSearchParams(new FormData(form));
  form.reset();
  let response;
  try {
    response = await fetch(form.action, {
      method: 'POST',
      headers: { 'HX-Request': 'true' },
      body,
    });
  } catch {
    return;
  }
  if (!response.ok) return;
  const wasTabs = into.classList.contains('tabs');
  const html = await response.text();
  if (form.getAttribute('hx-swap') === 'outerHTML') into.outerHTML = html;
  else into.innerHTML = html;
  swapped(wasTabs);
});

/* --- the width of the columns ------------------------------------------------------------------ */
// How much of the screen the middle deserves depends on the screen and on what is being read, so
// it is not a decision this file gets to make once. Drag a handle to set it, double-click to put
// it back, and the browser remembers per machine — this is a local tool, and the width is a
// preference, not data.
const grid = document.querySelector('.desk-grid');
const WIDTHS = 'agent-desk:widths';

function setWidths(left, right) {
  const most = Math.max(240, innerWidth * 0.4);
  if (left !== null) grid.style.setProperty('--left', `${Math.min(Math.max(left, 180), most)}px`);
  if (right !== null) grid.style.setProperty('--right', `${Math.min(Math.max(right, 160), most)}px`);
}

try {
  const saved = JSON.parse(localStorage.getItem(WIDTHS) || 'null');
  if (saved) setWidths(saved.left, saved.right);
} catch {
  // A browser with storage switched off gets the defaults, which are fine.
}

function remember() {
  try {
    localStorage.setItem(
      WIDTHS,
      JSON.stringify({
        left: parseFloat(getComputedStyle(grid).getPropertyValue('--left')),
        right: parseFloat(getComputedStyle(grid).getPropertyValue('--right')),
      })
    );
  } catch {
    // Nothing to do: the widths still work for this window.
  }
}

for (const handle of document.querySelectorAll('.gutter')) {
  const side = handle.dataset.gutter;

  handle.addEventListener('pointerdown', (event) => {
    event.preventDefault();
    handle.setPointerCapture(event.pointerId);
    handle.classList.add('pulling');
    document.body.classList.add('pulling');
    const startX = event.clientX;
    const startLeft = grid.querySelector('.col-left').getBoundingClientRect().width;
    const startRight = grid.querySelector('.col-right').getBoundingClientRect().width;

    const move = (moved) => {
      const dx = moved.clientX - startX;
      if (side === 'left') setWidths(startLeft + dx, null);
      else setWidths(null, startRight - dx);
    };
    const done = () => {
      handle.removeEventListener('pointermove', move);
      handle.classList.remove('pulling');
      document.body.classList.remove('pulling');
      remember();
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', done, { once: true });
    handle.addEventListener('pointercancel', done, { once: true });
  });

  // The keyboard reaches this too: it is a control, and a control only a mouse can use is one
  // half of the window somebody cannot arrange.
  handle.addEventListener('keydown', (event) => {
    const step = event.shiftKey ? 48 : 16;
    const left = grid.querySelector('.col-left').getBoundingClientRect().width;
    const right = grid.querySelector('.col-right').getBoundingClientRect().width;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      const dx = event.key === 'ArrowRight' ? step : -step;
      if (side === 'left') setWidths(left + dx, null);
      else setWidths(null, right - dx);
      remember();
    }
  });

  handle.addEventListener('dblclick', () => {
    grid.style.removeProperty('--left');
    grid.style.removeProperty('--right');
    try {
      localStorage.removeItem(WIDTHS);
    } catch {
      // Same as above.
    }
  });
}

/* --- the stream ------------------------------------------------------------------------------ */
function checked() {
  lastChecked = Date.now();
  asof.textContent = `checked ${new Date().toLocaleTimeString()}`;
  state.textContent = '·';
  state.className = 'tiny';
  document.body.classList.remove('stale');
}

function lost(why) {
  // The reconnect attempt and the silence timer both fire while the server is down, and each has a
  // true thing to say; alternating them once a second is a board nobody can read.
  if (document.body.classList.contains('stale')) return;
  state.textContent = why;
  state.className = 'tiny lost';
  document.body.classList.add('stale');
}

const stream = new EventSource('/events');

// The board is pushed every couple of seconds whether or not anything changed, and replacing the
// column under somebody's hand is not a cosmetic problem: a browser fires no click at all when
// mousedown and mouseup land on different elements, so every rebuild is a click that silently
// does nothing — and a drag that was in flight is cancelled outright. Two rules, both cheap: the
// same board is not rebuilt, and a board is never rebuilt mid-drag.
let lastBoard = '';
stream.addEventListener('board', (event) => {
  checked();
  if (event.data === lastBoard || document.body.classList.contains('dragging-card')) return;
  lastBoard = event.data;
  document.getElementById('board').innerHTML = event.data;
  const waiting = document.querySelectorAll('.node.session.flagged').length;
  document.title = waiting ? `agent-desk (${waiting})` : 'agent-desk';
});
stream.addEventListener('blocks', (event) => {
  // Never while somebody is reading or typing inside it: replacing the column under a selection
  // loses it, and an answer is the one thing here anybody copies out.
  if (!document.getSelection().isCollapsed) return;
  if (document.activeElement.closest('#out')) return;
  const wasAtBottom = out.scrollHeight - out.scrollTop - out.clientHeight < 40;
  document.getElementById('blocks').innerHTML = event.data;
  if (window.htmx) htmx.process(document.getElementById('blocks'));
  showActiveThread();
  // Only if they were already there. Yanking somebody back to the newest answer while they are
  // reading an older one is the same mistake as replacing the text under their cursor.
  if (wasAtBottom) out.scrollTop = out.scrollHeight;
  checked();
});
stream.addEventListener('heartbeat', checked);
stream.onerror = () => lost('stream lost — reconnecting');
setInterval(() => {
  if (lastChecked && Date.now() - lastChecked > poll * 3 * 1000) lost('no update — stream stalled');
}, 1000);

/* --- chats ----------------------------------------------------------------------------------- */
// A tab is a thread. Every block is rendered with the thread it belongs to and the page shows one
// tab's worth — which keeps the event stream stateless: the server does not need to know which tab
// each browser is looking at.
function activeThread() {
  return document.querySelector('.tab.on')?.dataset.thread || '';
}

function showActiveThread() {
  const current = activeThread();
  for (const block of document.querySelectorAll('#blocks [data-thread]')) {
    block.hidden = block.dataset.thread !== current;
  }
  const said = [...document.querySelectorAll('#blocks [data-thread]')].some((b) => !b.hidden);
  out.classList.toggle('is-empty', !said && !pins.children.length);
  const field = document.getElementById('say-thread');
  if (field) field.value = current;
}

document.addEventListener('click', (event) => {
  // The × is a form of its own inside the tab; let it post rather than switching to the chat
  // somebody is closing.
  if (event.target.closest('.tab-close')) return;
  const tab = event.target.closest('.tab');
  if (!tab) return;
  for (const other of document.querySelectorAll('.tab')) other.classList.toggle('on', other === tab);
  clearPins();
  showActiveThread();
  out.scrollTop = out.scrollHeight;
  document.getElementById('ask-text').focus();
});

// htmx swaps two fragments into this page, and both need the same thing afterwards: the tab bar,
// where the chat somebody just created has to become the one they are looking at, and the output,
// where a new message has to be visible under the field that produced it.
function swapped(isTabs) {
  if (isTabs) {
    applyTabOrder();
    // The chat somebody just created is the one they are looking at, and it is the last one.
    const tabs = [...document.querySelectorAll('.tab')];
    for (const tab of tabs) tab.classList.toggle('on', tab === tabs[tabs.length - 1]);
    clearPins();
  }
  showActiveThread();
  out.scrollTop = out.scrollHeight;
}

document.body.addEventListener('htmx:afterSwap', (event) => {
  swapped(!!event.target?.classList?.contains('tabs'));
});

/* --- the order of the chats --------------------------------------------------------------------- */
// Tabs are dragged into the order somebody wants them in. That order is a preference rather than
// data — it says nothing about the subjects themselves — so it lives in this browser beside the
// column widths, and a machine that has never been dragged on gets them oldest first.
const TAB_ORDER = 'agent-desk:tab-order';

function rememberTabOrder() {
  try {
    localStorage.setItem(
      TAB_ORDER,
      JSON.stringify([...document.querySelectorAll('.tab')].map((tab) => tab.dataset.thread))
    );
  } catch {
    // The order still holds for this window.
  }
}

function applyTabOrder() {
  let wanted;
  try {
    wanted = JSON.parse(localStorage.getItem(TAB_ORDER) || 'null');
  } catch {
    return;
  }
  if (!Array.isArray(wanted)) return;
  const bar = document.querySelector('.tabs');
  if (!bar) return;
  const place = (tab) => {
    const at = wanted.indexOf(tab.dataset.thread);
    return at === -1 ? wanted.length : at; // A chat made since then goes to the end.
  };
  const tabs = [...bar.querySelectorAll('.tab')].sort((a, b) => place(a) - place(b));
  const adder = bar.querySelector('.tab-new');
  for (const tab of tabs) bar.insertBefore(tab, adder);
}

let draggedTab = null;

document.addEventListener('dragstart', (event) => {
  const tab = event.target.closest?.('.tab');
  if (!tab) return;
  draggedTab = tab;
  tab.classList.add('dragging');
  event.dataTransfer.effectAllowed = 'move';
  event.dataTransfer.setData('text/plain', tab.textContent.trim());
});

document.addEventListener('dragover', (event) => {
  if (!draggedTab) return;
  const over = event.target.closest?.('.tab');
  if (!over || over === draggedTab) return;
  event.preventDefault();
  const box = over.getBoundingClientRect();
  const after = event.clientX > box.left + box.width / 2;
  over.parentElement.insertBefore(draggedTab, after ? over.nextSibling : over);
});

document.addEventListener('dragend', () => {
  if (!draggedTab) return;
  draggedTab.classList.remove('dragging');
  draggedTab = null;
  rememberTabOrder();
});

/* --- carrying a card into the middle ---------------------------------------------------------- */
// Dropping a card here does two things at once, because they are the same thought: it shows what
// the card actually contains, and it says that what you type next is about that. Dragging it back
// out undoes both.
function pinnedTargets() {
  return [...pins.querySelectorAll('[data-kind]')]
    .map((pin) => `${pin.dataset.kind}:${pin.dataset.id}${pin.dataset.deep === 'yes' ? ':full' : ''}`)
    .join(',');
}

// Which earlier exchanges travel with the next message. Nothing does by default: every call is
// built from exactly what was asked for, which is what makes what it costs predictable and what
// it answered from explainable.
function attachedBlocks() {
  return [...document.querySelectorAll('#blocks .attach.on')]
    .map((button) => button.dataset.block)
    .join(',');
}

function syncTargets() {
  document.getElementById('say-targets').value = pinnedTargets();
  document.getElementById('say-history').value = attachedBlocks();
  const attached = document.querySelectorAll('#blocks .attach.on').length;
  const carried = pins.children.length + attached;
  const deep = pins.querySelectorAll('.pin.deep').length;
  document.getElementById('context-count').textContent = carried
    ? `carrying ${pins.children.length} card${pins.children.length === 1 ? '' : 's'}` +
      `${deep ? ` (${deep} in full)` : ''}` +
      `${attached ? ` and ${attached} earlier answer${attached === 1 ? '' : 's'}` : ''}`
    : '';
  document.querySelector('.context-strip').classList.toggle('on', carried > 0);
  showActiveThread();
}

function clearPins() {
  pins.innerHTML = '';
  for (const button of document.querySelectorAll('#blocks .attach.on')) {
    button.classList.remove('on');
    button.textContent = 'use as context';
  }
  syncTargets();
}

document.getElementById('clear-context').addEventListener('click', clearPins);

async function pin(card) {
  if (pins.querySelector(`[data-id="${CSS.escape(card.id)}"][data-kind="${card.kind}"]`)) return;
  const holder = document.createElement('div');
  holder.className = 'pin';
  holder.dataset.kind = card.kind;
  holder.dataset.id = card.id;
  holder.draggable = true;
  holder.dataset.deep = 'no';
  holder.innerHTML = `<div class="pin-head"><span class="pin-kind">${card.kind}</span>
    <span class="pin-label"></span>
    <button type="button" class="pin-deep" title="send its whole transcript, not just the summary">brief</button>
    <button type="button" class="pin-off" title="stop talking about this">×</button></div>
    <div class="pin-body">reading…</div>`;
  holder.querySelector('.pin-label').textContent = card.label || card.id;
  pins.appendChild(holder);
  syncTargets();

  try {
    const url = `/cards/${encodeURIComponent(card.kind)}?id=${encodeURIComponent(card.id)}`;
    const response = await fetch(url);
    holder.querySelector('.pin-body').innerHTML = response.ok
      ? await response.text()
      : '<p class="empty small">could not read this one</p>';
  } catch {
    holder.querySelector('.pin-body').innerHTML = '<p class="empty small">could not read this one</p>';
  }
  syncTargets();
}

document.addEventListener('click', (event) => {
  if (event.target.classList.contains('pin-off')) {
    event.target.closest('.pin').remove();
    syncTargets();
    return;
  }

  // Brief by default, and the whole transcript only when somebody says so: the difference is the
  // size of the prompt and how long the answer takes.
  if (event.target.classList.contains('pin-deep')) {
    const holder = event.target.closest('.pin');
    const deep = holder.dataset.deep !== 'yes';
    holder.dataset.deep = deep ? 'yes' : 'no';
    holder.classList.toggle('deep', deep);
    event.target.textContent = deep ? 'full' : 'brief';
    syncTargets();
    return;
  }

  if (event.target.classList.contains('attach')) {
    event.target.classList.toggle('on');
    event.target.textContent = event.target.classList.contains('on')
      ? 'in context'
      : 'use as context';
    syncTargets();
    return;
  }

  // Clicking a card is the same act as dragging it in: both mean "show me this one". The twist
  // is left alone, because opening a node and opening a card are different questions and the
  // triangle is the one control that has always meant the first.
  const opener = event.target.closest('.node-open');
  const name = event.target.closest('.card-name, .node-name');
  const card = (opener || name)?.closest('[data-kind]');
  if (!card) return;
  event.preventDefault();
  pin({ kind: card.dataset.kind, id: card.dataset.id, label: card.dataset.label });
});

let dragged = null;

document.addEventListener('dragstart', (event) => {
  const card = event.target.closest('[data-kind]');
  if (!card) return;
  dragged = {
    kind: card.dataset.kind,
    id: card.dataset.id,
    label: card.dataset.label,
    project: card.closest('.project')?.dataset.project,
    fromPins: !!card.closest('#pins'),
  };
  event.dataTransfer.setData('text/plain', card.dataset.label || '');
  event.dataTransfer.effectAllowed = 'copyMove';
  card.classList.add('dragging');
  document.body.classList.add('dragging-card');
});

document.addEventListener('dragend', (event) => {
  event.target.closest?.('[data-kind]')?.classList.remove('dragging');
  document.body.classList.remove('dragging-card');
  // Dropped outside the middle: that is how a card is taken back out of the conversation.
  if (dragged?.fromPins && !dragged.handled) {
    pins.querySelector(`[data-kind="${dragged.kind}"][data-id="${CSS.escape(dragged.id)}"]`)?.remove();
    syncTargets();
  }
  dragged = null;
});

function zoneOf(event) {
  return event.target.closest('#out, [data-drop="project"]');
}

document.addEventListener('dragover', (event) => {
  const zone = zoneOf(event);
  if (!zone || !dragged) return;
  event.preventDefault();
  zone.classList.add('drop-target');
});

document.addEventListener('dragleave', (event) => zoneOf(event)?.classList.remove('drop-target'));

document.addEventListener('drop', (event) => {
  const zone = zoneOf(event);
  if (!zone || !dragged) return;
  event.preventDefault();
  zone.classList.remove('drop-target');
  dragged.handled = true;

  if (zone.id === 'out') {
    if (!dragged.fromPins) pin(dragged);
    document.getElementById('ask-text').focus();
    return;
  }

  // Onto a project card: what travels is the repository the dragged card belongs to.
  const into = zone.dataset.project;
  const from = dragged.kind === 'project' ? dragged.id : dragged.project;
  if (!into || !from || into === from) return;
  fetch(`/projects/${encodeURIComponent(into)}/members`, {
    method: 'POST',
    headers: { 'HX-Request': 'true' },
    body: new URLSearchParams({ repo_key: from }),
  })
    .then((response) => (response.ok ? response.text() : null))
    .then((html) => { if (html) document.getElementById('board').innerHTML = html; });
});

/* --- the keyboard ----------------------------------------------------------------------------- */
// This window hovers over a terminal, and reaching for the mouse is what it exists to save.
document.addEventListener('keydown', (event) => {
  const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
  if (event.key === '/' && !typing) {
    event.preventDefault();
    document.getElementById('ask-text').focus();
  }
  if (event.key === 'Escape') {
    const panel = document.getElementById('message');
    if (panel.innerHTML.trim()) panel.innerHTML = '';
    else if (pins.children.length) clearPins();
    else document.activeElement.blur();
  }
});

// A question carries its pins with it, and once it has been asked they are spent: the next message
// is about whatever is dropped in after this answer, which is what "the last blocks" means.
document.getElementById('ask').addEventListener('submit', () => {
  document.getElementById('say-targets').value = pinnedTargets();
  document.getElementById('say-history').value = attachedBlocks();
  setTimeout(clearPins, 0);
});

applyTabOrder();
showActiveThread();
out.scrollTop = out.scrollHeight;
