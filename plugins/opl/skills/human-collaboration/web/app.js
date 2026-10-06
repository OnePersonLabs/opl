const $ = (selector) => document.querySelector(selector)
const el = (tag, text = '', className = '') => {
  const node = document.createElement(tag)
  if (text) node.textContent = text
  if (className) node.className = className
  return node
}
const button = (title, action, className = '') => {
  const node = el('button', title, className)
  node.type = 'button'
  node.addEventListener('click', action)
  return node
}
let token = sessionStorage.getItem('opl-human-token') || ''
const fragment = new URLSearchParams(location.hash.slice(1))
if (fragment.has('token')) {
  token = fragment.get('token')
  sessionStorage.setItem('opl-human-token', token)
  history.replaceState(null, '', location.pathname + location.search)
}
let snapshot, opened, view = 'All messages', generation = 0, saveTimer, snapshotRequest = 0
let sessionFilter = new URLSearchParams(location.search).get('session') || ''
let draft = '', draftVersion = 0, draftConflict = false, saving = null, sending = false
let draftKey = '', pendingSend = null
let answerDraft = {}
let lastQueueRender = ''
let openedSyncSignature = '', syncingDetails = false
let objectUrls = []
const notice = (message = '') => { $('#notice').textContent = message }
function cached(key) {
  try { return JSON.parse(localStorage.getItem(key) || 'null') } catch { return null }
}
function persist() {
  try { localStorage.setItem(draftKey, JSON.stringify({body: draft, answers: answerDraft, pendingSend})) }
  catch { notice('Device storage is unavailable. Save your draft to the workspace before leaving.') }
}
function requestId() {
  const bytes = new Uint8Array(16)
  crypto.getRandomValues(bytes)
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}
async function api(path, data, binary = false) {
  const response = await fetch(path, {method: data ? 'POST' : 'GET',
    headers: {Authorization: `Bearer ${token}`, ...(data ? {'Content-Type': 'application/json'} : {})},
    ...(data ? {body: JSON.stringify(data)} : {})})
  if (!response.ok) {
    const result = await response.json()
    const error = new Error(result.error || `Request failed (${response.status})`)
    error.status = response.status
    if (response.status === 401) $('#pairing').hidden = false
    throw error
  }
  return binary ? response : response.json()
}
function inline(node, value) {
  // Text and a small Markdown subset only. Raw HTML is never inserted.
  const pattern = /(\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\((https?:\/\/[^\s)]+)\))/g
  let offset = 0
  for (const match of value.matchAll(pattern)) {
    node.append(document.createTextNode(value.slice(offset, match.index)))
    if (match[2]) node.append(el('strong', match[2]))
    else if (match[3]) node.append(el('code', match[3]))
    else {
      const link = el('a', match[4]); link.href = match[5]; link.target = '_blank'; link.rel = 'noopener noreferrer'
      node.append(link)
    }
    offset = match.index + match[0].length
  }
  node.append(document.createTextNode(value.slice(offset)))
}
async function imageFor(node, index, item, caption) {
  try {
    const response = await api(itemUrl('/api/source', item, {revision: item.viewed_revision, index}), null, true)
    const url = URL.createObjectURL(await response.blob()); objectUrls.push(url)
    const image = el('img', '', 'diagram'); image.src = url; image.alt = caption; image.loading = 'lazy'
    if (node.isConnected) node.replaceChildren(image)
  } catch (error) { node.textContent = `Diagram unavailable: ${error.message}` }
}
function markdown(value, item) {
  const root = el('div', '', 'brief')
  const lines = value.replaceAll('\r\n', '\n').split('\n')
  let paragraph = [], code = null, list = null
  function flush() { if (paragraph.length) { const p = el('p'); inline(p, paragraph.join(' ')); root.append(p); paragraph = [] } }
  for (const line of lines) {
    if (line.startsWith('```')) {
      flush(); list = null
      if (code === null) code = []
      else { const pre = el('pre'); pre.append(el('code', code.join('\n'))); root.append(pre); code = null }
      continue
    }
    if (code !== null) { code.push(line); continue }
    if (!line.trim()) { flush(); list = null; continue }
    const heading = line.match(/^(#{1,4})\s+(.+)$/)
    const entry = line.match(/^(?:[-*]|\d+\.)\s+(.+)$/)
    const image = line.match(/^!\[([^\]]*)\]\(([^)]+)\)$/)
    if (heading) { flush(); list = null; const h = el(`h${heading[1].length}`); inline(h, heading[2]); root.append(h) }
    else if (image && item) {
      flush(); list = null
      const relative = image[2].replace(/^(\.\.\/)+/, '')
      const index = relative.startsWith('source:') ? Number(relative.slice(7)) : item.sources.findIndex((source) => source.path === relative)
      const holder = el('div', image[1] || 'Diagram'); root.append(holder)
      if (Number.isInteger(index) && item.sources[index]?.mime.startsWith('image/')) void imageFor(holder, index, item, image[1])
    } else if (entry) {
      flush(); const type = /^\d/.test(line) ? 'ol' : 'ul'
      if (!list || list.tagName.toLowerCase() !== type) { list = el(type); root.append(list) }
      const li = el('li'); inline(li, entry[1]); list.append(li)
    } else if (line.startsWith('> ')) { flush(); const quote = el('blockquote'); inline(quote, line.slice(2)); root.append(quote) }
    else paragraph.push(line)
  }
  flush()
  if (code !== null) root.append(el('pre', code.join('\n')))
  return root
}
function itemUrl(path, item, extra = {}) {
  return `${path}?${new URLSearchParams({id: item.id, workspace: item.workspace_id, ...extra})}`
}
function locationFor(item) {
  const query = new URLSearchParams()
  if (sessionFilter) query.set('session', sessionFilter)
  if (item) {
    query.set('workspace', item.workspace_id); query.set('item', item.id)
    query.set('revision', item.viewed_revision)
  }
  return `/${query.size ? `?${query}` : ''}`
}
async function selectSession(id) {
  clearTimeout(saveTimer)
  if (saving) await saving
  ++generation; opened = null; sessionFilter = id
  $('#detail').hidden = true; $('#app').classList.remove('detail-open')
  history.replaceState(null, '', locationFor())
  renderQueue()
}
function renderSessions() {
  const sessions = snapshot.sessions.filter((session) => snapshot.items.some((item) => item.session === session.id))
  const count = sessions.reduce((sum, session) => sum + session.needs_you, 0)
  const all = button(`All sessions · ${count} need you`, () => selectSession(''), 'session-option')
  all.setAttribute('aria-pressed', String(!sessionFilter))
  const rows = sessions.map((session) => {
    const row = button('', () => selectSession(session.id), 'session-option')
    row.dataset.session = session.id
    row.setAttribute('aria-pressed', String(sessionFilter === session.id))
    row.append(el('strong', session.title))
    const status = session.needs_you ? `${session.needs_you} need you` : 'No pending questions'
    row.append(el('span', `${status} · ${session.with_agent} with agent${session.assumed ? ` · ${session.assumed} answer assumed` : ''}`, session.needs_you ? 'session-status pending' : 'session-status'))
    const context = el('span', `${session.workspace}${session.later ? ` · ${session.later} later` : ''}`, 'session-context')
    row.append(context)
    return row
  })
  $('#sessions').replaceChildren(all, ...rows)
}
function itemRow(item) {
  const row = el('section', '', 'item')
  row.dataset.workspace = item.workspace_id; row.dataset.session = item.session
  row.dataset.item = item.id
  row.append(el('div', item.session_title, 'session-label'))
  row.append(el('div', `${item.id} · ${item.kind} · ${item.state.replace('_', ' ')}`, 'meta'))
  row.append(button(item.title, () => openItem(item.id, undefined, item.workspace_id)))
  row.append(el('p', item.summary))
  row.append(el('p', `Why now: ${item.why_now}`, 'why'))
  if (item.blocking || item.has_draft) row.append(el('p', [item.blocking && 'Blocks related work', item.has_draft && 'Draft in progress'].filter(Boolean).join(' · '), 'flag'))
  return row
}
function messageRow(message) {
  const row = el('section', '', 'item feed-message')
  row.dataset.workspace = message.workspace_id; row.dataset.session = message.session
  row.dataset.message = message.id
  row.append(el('div', `${message.session_title} · ${message.role === 'you' ? 'You' : 'Agent'} · ${message.kind.replaceAll('_', ' ')}`, 'meta'))
  const time = el('time', new Date(message.created).toLocaleString([], {dateStyle: 'short', timeStyle: 'short'}), 'message-time')
  time.dateTime = message.created; row.append(time)
  row.append(button(message.title, () => openItem(message.item, message.revision, message.workspace_id)))
  row.append(el('p', message.text, 'message-preview'))
  return row
}
function renderQueue() {
  const signature = JSON.stringify([snapshot.items, snapshot.sessions, snapshot.messages, sessionFilter, view])
  if (signature === lastQueueRender) return
  lastQueueRender = signature
  const active = document.activeElement
  const focusedSession = active.closest('#sessions [data-session]')?.dataset.session
  const focusedMessage = active.closest('[data-message]')?.dataset.message
  const focusedItem = active.closest('[data-item]')
  const focusedView = active.closest('#tabs') ? active.textContent : null
  const restoreFocus = () => {
    const escaped = (value) => CSS.escape(value)
    const target = focusedSession ? $(`#sessions [data-session="${escaped(focusedSession)}"]`) :
      focusedMessage ? $(`[data-message="${escaped(focusedMessage)}"] button`) :
      focusedItem ? $(`[data-workspace="${escaped(focusedItem.dataset.workspace)}"][data-item="${escaped(focusedItem.dataset.item)}"] button`) :
      focusedView ? [...$('#tabs').children].find((node) => node.textContent === focusedView) : null
    if (target) target.focus({preventScroll: true})
  }
  renderSessions()
  const views = ['Needs you', 'With agent', 'All messages', 'Decisions', 'Closed']
  $('#tabs').replaceChildren(...views.map((name) => {
    const node = button(name, () => { view = name; renderQueue() })
    node.setAttribute('aria-pressed', String(view === name)); return node
  }))
  $('#view-title').textContent = view
  const help = {'Needs you': 'Prepared work where your input can make a difference.', 'With agent': 'You have replied. The owning session owes you an outcome.', 'All messages': 'Every contribution and its conversation, including completed work.', Decisions: 'Consequential choices, including the settled ones. IDs never change with rank.', Closed: 'Outcomes and retired work remain available.'}
  $('#view-help').textContent = help[view]
  const items = snapshot.items.filter((item) => !sessionFilter || item.session === sessionFilter)
  if (view === 'All messages') {
    const messages = snapshot.messages.filter((message) => !sessionFilter || message.session === sessionFilter)
    $('#items').replaceChildren(...messages.map(messageRow))
    if (!messages.length) $('#items').append(el('p', 'No messages in this view yet.', 'empty'))
    restoreFocus()
    return
  }
  let selected = items.filter((item) => view === 'All messages' ? true : view === 'Decisions' ? item.decision : view === 'With agent' ? item.state === 'with_agent' : view === 'Closed' ? ['resolved','retired'].includes(item.state) : ['ready','active'].includes(item.state))
  let later = []
  if (view === 'Needs you') {
    const important = selected.filter((item) => item.blocking || item.state === 'active' || item.has_draft)
    const ordinary = selected.filter((item) => !important.includes(item))
    selected = [...important, ...ordinary.slice(0, 3)]
    later = [...ordinary.slice(3), ...items.filter((item) => ['candidate','deferred'].includes(item.state))]
  }
  $('#items').replaceChildren(...selected.map(itemRow))
  if (!selected.length) $('#items').append(el('p', view === 'Needs you' ? 'Nothing needs your attention right now.' : 'Nothing here yet.', 'empty'))
  if (later.length) {
    const fold = el('details'); fold.append(el('summary', `Later (${later.length})`), ...later.map(itemRow)); $('#items').append(fold)
  }
  restoreFocus()
}
async function refresh(quiet = false) {
  const request = ++snapshotRequest
  try {
    const next = await api('/api/inbox')
    if (request !== snapshotRequest) return
    snapshot = next
    if (sessionFilter && !snapshot.sessions.some((session) => session.id === sessionFilter)) sessionFilter = ''
    const projects = new Map(snapshot.items.map((item) => [item.workspace_id, item.workspace]))
    $('#workspace').textContent = projects.size === 1 ? projects.values().next().value : projects.size ? `${projects.size} projects` : 'No contributions yet'
    $('#app').hidden = false; $('#pairing').hidden = true
    renderQueue()
    $('#live-status').textContent = 'Live · updates every 3 seconds'
    if (!quiet) {
      notice()
      if (opened) await openItem(opened.id, opened.viewed_revision, opened.workspace_id)
    } else await syncOpenedReadOnly()
  } catch (error) {
    $('#live-status').textContent = 'Disconnected · retrying while this view is open'
    if (!quiet || error.status === 401) notice(error.message)
  }
}
function draftStatus(message, conflict = false) {
  const node = $('#draft-status')
  if (node) { node.textContent = message; node.classList.toggle('draft-conflict', conflict) }
}
function sameAnswers(left = {}, right = {}) {
  const ordered = (value) => JSON.stringify(Object.keys(value).sort().map((key) => [key, value[key]]))
  return ordered(left) === ordered(right)
}
function draftEdited() {
  pendingSend = null; persist(); draftStatus('Draft saved on this device.')
  clearTimeout(saveTimer); saveTimer = setTimeout(saveDraft, 700)
}
function answerText(question, answer) {
  return answer?.text ?? question.options[answer?.option] ?? ''
}
function questionStatus(node, question) {
  node.hidden = question.state === 'open'
  node.className = `question-status ${question.state === 'answer_assumed' ? 'warning' : 'muted'}`
  const status = question.state === 'answer_assumed' ? 'Answer assumed' : 'Answered'
  const value = node.hidden ? '' : `${status}: ${answerText(question, question.answer)}${question.reason ? ` · ${question.reason}` : ''}`
  if (node.textContent !== value) node.textContent = value
}
function detailSignature(item) {
  const current = snapshot.items.find((entry) => entry.workspace_id === item.workspace_id && entry.id === item.id)
  const messages = snapshot.messages.filter((entry) => entry.workspace_id === item.workspace_id && entry.item === item.id)
  return JSON.stringify([current?.state, current?.questions, messages.map((entry) => entry.id), snapshot.event])
}
async function syncOpenedReadOnly() {
  if (!opened || syncingDetails || sending) return
  const previous = opened, signature = detailSignature(previous), ownGeneration = generation
  if (signature === openedSyncSignature) return
  syncingDetails = true
  try {
    const item = await api(itemUrl('/api/item', previous, {revision: previous.viewed_revision}))
    if (ownGeneration !== generation || !opened || opened.workspace_id !== item.workspace_id || opened.id !== item.id) return
    openedSyncSignature = signature
    opened = item
    const detail = $('#detail')
    detail.querySelector('.detail-meta').textContent = `${item.session_title} · ${item.id} · revision ${item.viewed_revision} · ${item.state.replace('_',' ')}`
    detail.querySelector('.conversation').replaceWith(conversationFor(item))
    for (const question of item.questions || []) {
      const status = detail.querySelector(`[data-question="${CSS.escape(question.id)}"] .question-status`)
      if (status) questionStatus(status, question)
    }
  } catch (error) {
    notice(`Your draft is retained. Conversation updates are unavailable: ${error.message}`)
  } finally { syncingDetails = false }
}
function conversationFor(item) {
  const conversation = el('section', '', 'conversation'); conversation.append(el('h2', 'Conversation & outcomes'))
  if (!item.submissions.length) conversation.append(el('p', 'Ask a question, challenge the premise, or send a decision. A draft is not a submission.', 'muted'))
  for (const submission of item.submissions) {
    const human = el('div', '', 'message human')
    const queue = JSON.parse(submission.queue)
    human.append(el('div', `You · ${submission.kind} · v${submission.revision} · ${submission.state}${queue.state !== 'not_requested' ? ` · notification ${queue.state}` : ''}`, 'meta'), markdown(submission.body))
    const answers = typeof submission.answers === 'string' ? JSON.parse(submission.answers) : submission.answers || {}
    for (const [id, answer] of Object.entries(answers)) {
      const question = submission.questions?.find((entry) => entry.id === id)
      human.append(el('p', `${question?.prompt || id}: ${question ? answerText(question, answer) : answer.text ?? `Option ${answer.option + 1}`}`))
    }
    conversation.append(human)
    const outcome = item.outcomes.find((candidate) => candidate.submission === submission.id)
    if (outcome) {
      const answer = el('div', '', 'message')
      answer.append(el('div', `Root · ${outcome.disposition.replace('_',' ')}`, 'meta'), markdown(outcome.text), el('p', `Source review: ${outcome.source_review}`, 'muted'))
      if (outcome.references.length) answer.append(markdown(outcome.references.map((ref) => `- ${ref}`).join('\n')))
      conversation.append(answer)
    }
  }
  return conversation
}
function questionFields(item) {
  const section = el('section', '', 'questions')
  section.append(el('h2', 'Questions'))
  for (const question of item.questions) {
    const field = el('fieldset', '', 'question'); field.dataset.question = question.id
    field.append(el('legend', question.prompt))
    const status = el('p'); status.setAttribute('aria-live', 'polite'); questionStatus(status, question); field.append(status)
    for (let index = 0; index < 4; index++) {
      const choice = el('label', '', 'question-choice'), radio = el('input')
      radio.type = 'radio'; radio.name = `question-${question.id}`; radio.value = String(index)
      const saved = answerDraft[question.id]
      radio.checked = index < 3 ? saved?.option === index : typeof saved?.text === 'string'
      choice.append(radio, el('span', index === 3 ? 'Your own answer' : `${question.options[index]}${index === 0 ? ' (Recommended)' : ''}`))
      field.append(choice)
      if (index < 3) radio.addEventListener('change', () => { answerDraft = {...answerDraft, [question.id]: {option: index}}; draftEdited() })
      else {
        const input = el('textarea'); input.className = 'question-text'; input.value = saved?.text || ''
        input.setAttribute('aria-label', `Your own answer: ${question.prompt}`)
        input.placeholder = 'Write your answer'
        const update = () => {
          radio.checked = true
          if (input.value.trim()) answerDraft = {...answerDraft, [question.id]: {text: input.value}}
          else delete answerDraft[question.id]
          draftEdited()
        }
        radio.addEventListener('change', () => { update(); input.focus() })
        input.addEventListener('input', update); field.append(input)
      }
    }
    section.append(field)
  }
  return section
}
async function saveDraft() {
  clearTimeout(saveTimer)
  if (!opened || draftConflict || sending) return
  if (saving) return saving
  const item = opened, body = draft, answers = structuredClone(answerDraft), version = draftVersion, key = draftKey
  saving = (async () => {
    try {
      const result = await api('/api/draft', {workspace: item.workspace_id, id: item.id, revision: item.viewed_revision, body, answers, expected: version})
      if (draftKey !== key) return
      draftVersion = result.version
      const unchanged = draft === body && sameAnswers(answerDraft, answers)
      draftStatus(unchanged ? 'Draft saved to workspace and this device.' : 'Saving your latest edit…')
      if (!unchanged) saveTimer = setTimeout(saveDraft, 500)
    } catch (error) {
      if (draftKey !== key) return
      if (error.status === 409) draftConflict = true
      draftStatus(`Saved on this device only. ${error.message}`, true)
    } finally { saving = null }
  })()
  return saving
}
async function sendReply() {
  if (sending || (!draft.trim() && !Object.keys(answerDraft).length) || !opened) return
  clearTimeout(saveTimer)
  if (saving) await saving
  if (draftConflict) { notice('Resolve the draft conflict before sending. Your text is still on this device.'); return }
  const item = opened, body = draft, answers = structuredClone(answerDraft), kind = $('#reply-kind').value
  if (!pendingSend || pendingSend.body !== body || pendingSend.kind !== kind || !sameAnswers(pendingSend.answers, answers)) pendingSend = {request_id: requestId(), body, answers, kind}
  persist(); sending = true; $('#send').disabled = true
  const key = draftKey
  try {
    const receipt = await api('/api/submit', {workspace: item.workspace_id, id: item.id, revision: item.viewed_revision, ...pendingSend})
    if (draftKey === key && draft === body && sameAnswers(answerDraft, answers)) {
      draft = ''; answerDraft = {}; pendingSend = null; persist()
    }
    notice(`Saved as ${receipt.id.slice(0, 8)}. With agent; not yet incorporated.`)
    await openItem(item.id, item.viewed_revision, item.workspace_id)
    snapshot = await api('/api/inbox'); renderQueue()
  } catch (error) { notice(`Reply retained for retry. ${error.message}`) }
  finally { sending = false; if ($('#send')) $('#send').disabled = false }
}
async function queueAction(action) {
  const reason = action === 'start' ? '' : prompt(action === 'later' ? 'Why defer this item?' : 'Why reopen or return this item to the queue?')
  if (reason === null || (action !== 'start' && !reason.trim())) return
  try { await api('/api/action', {workspace: opened.workspace_id, id: opened.id, action, reason}); await refresh() }
  catch (error) { notice(error.message) }
}
async function openItem(id, revision, workspace = snapshot.workspace_id) {
  clearTimeout(saveTimer)
  if (saving) await saving
  const ownGeneration = ++generation
  try {
    const item = await api(`/api/item?${new URLSearchParams({id, workspace, ...(revision ? {revision} : {})})}`)
    if (ownGeneration !== generation) return
    for (const url of objectUrls) URL.revokeObjectURL(url)
    objectUrls = []; opened = item; openedSyncSignature = detailSignature(item)
    draftKey = `opl-human:${item.workspace_id}:${item.id}:v${item.viewed_revision}`
    const local = cached(draftKey)
    draft = local?.body ?? item.drafts.web.body
    answerDraft = local?.answers ?? item.drafts.web.answers ?? {}
    pendingSend = local?.pendingSend ?? null
    draftVersion = item.drafts.web.version
    const serverDraft = Boolean(item.drafts.web.body || Object.keys(item.drafts.web.answers || {}).length)
    draftConflict = Boolean(local && serverDraft && (local.body !== item.drafts.web.body || !sameAnswers(local.answers, item.drafts.web.answers)))
    const detail = $('#detail'); detail.replaceChildren(); detail.hidden = false; $('#app').classList.add('detail-open')
    history.replaceState(null, '', locationFor(item))
    detail.append(button('Back to inbox', () => {
      ++generation; clearTimeout(saveTimer); opened = null; detail.hidden = true; $('#app').classList.remove('detail-open'); history.replaceState(null, '', locationFor())
    }, 'back'))
    detail.append(el('div', `${item.session_title} · ${item.id} · revision ${item.viewed_revision} · ${item.state.replace('_',' ')}`, 'detail-meta'), el('h1', item.title), el('p', item.summary, 'detail-summary'))
    const toolbar = el('div', '', 'toolbar')
    if (item.prepared && ['ready','deferred'].includes(item.state)) toolbar.append(button('Start', () => queueAction('start')))
    if (['ready','active'].includes(item.state)) toolbar.append(button('Later', () => queueAction('later')))
    if (item.prepared && ['resolved','retired','deferred'].includes(item.state)) toolbar.append(button('Return to queue', () => queueAction('ready')))
    detail.append(toolbar)
    if (!item.prepared) detail.append(el('p', 'The root has not prepared this brief for review. Existing drafts are retained; it cannot be started or submitted yet.', 'warning'))
    if (item.revisions.length > 1) {
      const label = el('label', 'Brief revision '), versions = el('select')
      versions.setAttribute('aria-label', 'Brief revision')
      for (const entry of item.revisions) {
        const option = el('option', `Revision ${entry.revision}${entry.has_draft ? ' · draft' : ''}${entry.file_error ? ' · file needs attention' : ''}`)
        option.value = String(entry.revision); option.selected = entry.revision === item.viewed_revision
        versions.append(option)
      }
      versions.addEventListener('change', () => { void openItem(item.id, Number(versions.value), item.workspace_id) })
      label.append(versions); detail.append(label)
    }
    if (item.viewed_revision !== item.revision || item.source_status.some((source) => source.changed)) detail.append(el('p', 'Context changed since this brief was published. Your reply remains attached to the version shown, not the newer code.', 'warning'))
    if (item.drafts.file_error) detail.append(el('p', item.drafts.file_error, 'warning'))
    if (item.drafts.file_pending) detail.append(el('p', 'There is also an unsent draft under # Reply in the Markdown file. This phone draft is separate; neither overwrites the other.', 'warning'))
    detail.append(markdown(item.brief, item))
    if (item.sources.length) {
      const sources = el('section', '', 'sources'); sources.append(el('h2', 'Grounded sources'))
      item.sources.forEach((source, index) => {
        const row = el('div', '', 'source'); row.append(el('div', `${source.path}${item.source_status[index].changed ? ' · changed' : ''}`, 'source-name'))
        for (const live of [false, true]) row.append(button(live ? 'Current file' : 'Reviewed snapshot', async () => {
          try {
            const response = await api(itemUrl('/api/source', item, {revision: item.viewed_revision, index, ...(live ? {live: 1} : {})}), null, true)
            row.querySelectorAll('.source-code,.diagram').forEach((node) => node.remove())
            if (source.mime.startsWith('image/')) {
              const url = URL.createObjectURL(await response.blob()); objectUrls.push(url)
              const image = el('img', '', 'diagram'); image.src = url; image.alt = `${live ? 'Current' : 'Reviewed'} ${source.path}`; row.append(image)
            } else row.append(el('pre', await response.text(), 'source-code'))
          } catch (error) { notice(error.message) }
        }))
        sources.append(row)
      })
      detail.append(sources)
    }
    detail.append(conversationFor(item))
    if (item.prepared) {
      if (item.questions?.length) detail.append(questionFields(item))
      const composer = el('section', '', 'composer')
      const caption = el('label', 'Your reply'); caption.htmlFor = 'reply'
      const input = el('textarea'); input.id = 'reply'; input.value = draft; input.placeholder = '“#6 combines two different responsibilities. Split them here…”'
      input.addEventListener('input', () => { draft = input.value; draftEdited() })
      composer.append(caption, input)
      const actions = el('div', '', 'composer-actions'), select = el('select'); select.id = 'reply-kind'; select.setAttribute('aria-label', 'Reply type')
      for (const name of ['feedback','question']) { const option = el('option', name === 'feedback' ? 'Feedback / decision' : 'Question'); option.value = name; select.append(option) }
      if (pendingSend) select.value = pendingSend.kind
      actions.append(select, button('Save draft', saveDraft), button('Send', sendReply, 'primary')); actions.lastChild.id = 'send'
      const status = el('div', '', 'draft-status'); status.id = 'draft-status'; status.setAttribute('aria-live','polite')
      composer.append(actions, status)
      if (draftConflict) {
        composer.append(el('p', 'This device and the workspace have different drafts. Choose explicitly; neither has been overwritten.', 'warning'))
        composer.append(button('Keep this device draft', () => { draftConflict = false; void saveDraft() }), button('Use workspace draft', () => {
          draft = item.drafts.web.body; answerDraft = item.drafts.web.answers || {}; input.value = draft
          pendingSend = null; draftConflict = false; persist()
          const existing = detail.querySelector('.questions')
          if (existing) existing.replaceWith(questionFields(item))
          draftStatus('Workspace draft loaded.')
        }))
      }
      detail.append(composer)
      draftStatus(draftConflict ? 'Draft conflict; choose which version to keep.' : draft ? 'Draft restored.' : 'Send submits explicitly. Saving does not instruct the agent.', draftConflict)
    }
    detail.append(el('p', `Published filesystem mtime_ns: ${item.published_mtime_ns} · observed: ${item.observed_mtime_ns}`, 'stamp'))
  } catch (error) { notice(error.message) }
}
async function newContribution() {
  clearTimeout(saveTimer)
  if (saving) await saving
  const sessions = snapshot.sessions
  if (!sessions.length) { notice('Register a session before starting a contribution.'); return }
  const target = el('select'); target.id = 'contribution-session'
  const placeholder = el('option', 'Choose a session'); placeholder.value = ''; target.append(placeholder)
  for (const session of sessions) {
    const option = el('option', `${session.title} · ${session.workspace}`)
    option.value = session.id; target.append(option)
  }
  target.value = sessionFilter || (sessions.length === 1 ? sessions[0].id : '')
  let key, local
  const loadDraft = () => {
    key = `opl-human:new:${target.value || 'unassigned'}`
    local = cached(key) || (sessions.length === 1 ? cached(`opl-human:${sessions[0].workspace_id}:new`) : null) || {title: '', body: '', request_id: requestId()}
  }
  loadDraft()
  const detail = $('#detail'); detail.replaceChildren(); detail.hidden = false
  ++generation; opened = null; $('#app').classList.add('detail-open')
  const title = el('input'); title.id = 'new-title'; title.value = local.title
  const body = el('textarea'); body.id = 'new-body'; body.value = local.body
  const titleLabel = el('label', 'Subject'); titleLabel.htmlFor = title.id
  const bodyLabel = el('label', 'Your contribution'); bodyLabel.htmlFor = body.id
  const store = () => {
    local = {title: title.value, body: body.value, request_id: requestId()}
    try { localStorage.setItem(key, JSON.stringify(local)) } catch { notice('Device storage is unavailable. Keep this page open until submitted.') }
  }
  title.addEventListener('input', store); body.addEventListener('input', store)
  target.addEventListener('change', () => { loadDraft(); title.value = local.title; body.value = local.body })
  const send = button('Send contribution', async () => {
    if (!target.value) { notice('Choose the session that should receive your contribution.'); return }
    if (!title.value.trim() || !body.value.trim()) { notice('Add a subject and your contribution.'); return }
    send.disabled = true
    try {
      const session = sessions.find((candidate) => candidate.id === target.value)
      const receipt = await api('/api/contribute', {...local, session: session.id, workspace: session.workspace_id})
      localStorage.removeItem(key); snapshot = await api('/api/inbox'); renderQueue()
      if (sessions.length === 1) localStorage.removeItem(`opl-human:${session.workspace_id}:new`)
      await openItem(`H${String(receipt.item).padStart(3, '0')}`, undefined, session.workspace_id)
      notice('Your contribution is saved. The root owes you an outcome.')
    } catch (error) { notice(`Contribution retained for retry. ${error.message}`) }
    finally { send.disabled = false }
  }, 'primary')
  detail.append(button('Back to inbox', () => { detail.hidden = true; $('#app').classList.remove('detail-open') }, 'back'),
    el('h1', 'Start a contribution'), el('p', 'Raise a decision, challenge an assumption, or bring in something the agent has not asked about.'),
    el('label', 'Send to session'), target, titleLabel, title, bodyLabel, body, send)
  detail.querySelector('label').htmlFor = target.id
}
$('#contribute').addEventListener('click', newContribution)
$('#refresh').addEventListener('click', () => refresh())
$('#pair-form').addEventListener('submit', async (event) => {
  event.preventDefault(); token = $('#token').value.trim(); sessionStorage.setItem('opl-human-token', token); await refresh()
})
await refresh()
const initial = new URLSearchParams(location.search)
if (snapshot && initial.has('item')) await openItem(initial.get('item'), Number(initial.get('revision')) || undefined, initial.get('workspace') || snapshot.workspace_id)
// Only the browser polls. Snapshot refreshes leave the open composer intact.
setInterval(() => { if (!document.hidden && token) void refresh(true) }, 3000)
document.addEventListener('visibilitychange', () => { if (!document.hidden && token) void refresh(true) })
window.addEventListener('focus', () => { if (token) void refresh(true) })
