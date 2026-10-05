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
let snapshot, opened, view = 'Needs you', generation = 0, saveTimer
let draft = '', draftVersion = 0, draftConflict = false, saving = null, sending = false
let draftKey = '', pendingSend = null
let objectUrls = []
const notice = (message = '') => { $('#notice').textContent = message }
function cached(key) {
  try { return JSON.parse(localStorage.getItem(key) || 'null') } catch { return null }
}
function persist() {
  try { localStorage.setItem(draftKey, JSON.stringify({body: draft, pendingSend})) }
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
    const response = await api(`/api/source?id=${item.id}&revision=${item.viewed_revision}&index=${index}`, null, true)
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
function itemRow(item) {
  const row = el('section', '', 'item')
  row.append(el('div', `${item.id} · ${item.kind} · ${item.state.replace('_', ' ')}`, 'meta'))
  row.append(button(item.title, () => openItem(item.id)))
  row.append(el('p', item.summary))
  row.append(el('p', `Why now: ${item.why_now}`, 'why'))
  if (item.blocking || item.has_draft) row.append(el('p', [item.blocking && 'Blocks related work', item.has_draft && 'Draft in progress'].filter(Boolean).join(' · '), 'flag'))
  return row
}
function renderQueue() {
  const views = ['Needs you', 'With agent', 'Decisions', 'Closed']
  $('#tabs').replaceChildren(...views.map((name) => {
    const node = button(name, () => { view = name; renderQueue() })
    node.setAttribute('aria-pressed', String(view === name)); return node
  }))
  $('#view-title').textContent = view
  const help = {'Needs you': 'Prepared work where your input can make a difference.', 'With agent': 'You have replied. The root owes you an outcome.', Decisions: 'Consequential choices, including the settled ones. IDs never change with rank.', Closed: 'Outcomes and retired work remain available.'}
  $('#view-help').textContent = help[view]
  const items = snapshot.items
  let selected = items.filter((item) => view === 'Decisions' ? item.decision : view === 'With agent' ? item.state === 'with_agent' : view === 'Closed' ? ['resolved','retired'].includes(item.state) : ['ready','active'].includes(item.state))
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
}
async function refresh() {
  try {
    snapshot = await api('/api/inbox')
    $('#workspace').textContent = snapshot.workspace
    $('#app').hidden = false; $('#pairing').hidden = true
    renderQueue(); notice()
    if (opened) await openItem(opened.id, opened.viewed_revision)
  } catch (error) { notice(error.message) }
}
function draftStatus(message, conflict = false) {
  const node = $('#draft-status')
  if (node) { node.textContent = message; node.classList.toggle('draft-conflict', conflict) }
}
async function saveDraft() {
  clearTimeout(saveTimer)
  if (!opened || draftConflict || sending) return
  if (saving) return saving
  const item = opened, body = draft, version = draftVersion, key = draftKey
  saving = (async () => {
    try {
      const result = await api('/api/draft', {id: item.id, revision: item.viewed_revision, body, expected: version})
      if (draftKey !== key) return
      draftVersion = result.version
      draftStatus(draft === body ? 'Draft saved to workspace and this device.' : 'Saving your latest edit…')
      if (draft !== body) saveTimer = setTimeout(saveDraft, 500)
    } catch (error) {
      if (draftKey !== key) return
      if (error.status === 409) draftConflict = true
      draftStatus(`Saved on this device only. ${error.message}`, true)
    } finally { saving = null }
  })()
  return saving
}
async function sendReply() {
  if (sending || !draft.trim() || !opened) return
  clearTimeout(saveTimer)
  if (saving) await saving
  if (draftConflict) { notice('Resolve the draft conflict before sending. Your text is still on this device.'); return }
  const item = opened, body = draft, kind = $('#reply-kind').value
  if (!pendingSend || pendingSend.body !== body || pendingSend.kind !== kind) pendingSend = {request_id: requestId(), body, kind}
  persist(); sending = true; $('#send').disabled = true
  const key = draftKey
  try {
    const receipt = await api('/api/submit', {id: item.id, revision: item.viewed_revision, ...pendingSend})
    if (draftKey === key && draft === body) {
      draft = ''; pendingSend = null; persist()
    }
    notice(`Saved as ${receipt.id.slice(0, 8)}. With agent; not yet incorporated.`)
    await openItem(item.id, item.viewed_revision)
    snapshot = await api('/api/inbox'); renderQueue()
  } catch (error) { notice(`Reply retained for retry. ${error.message}`) }
  finally { sending = false; if ($('#send')) $('#send').disabled = false }
}
async function queueAction(action) {
  const reason = action === 'start' ? '' : prompt(action === 'later' ? 'Why defer this item?' : 'Why reopen or return this item to the queue?')
  if (reason === null || (action !== 'start' && !reason.trim())) return
  try { await api('/api/action', {id: opened.id, action, reason}); await refresh() }
  catch (error) { notice(error.message) }
}
async function openItem(id, revision) {
  clearTimeout(saveTimer)
  if (saving) await saving
  const ownGeneration = ++generation
  try {
    const item = await api(`/api/item?id=${encodeURIComponent(id)}${revision ? `&revision=${revision}` : ''}`)
    if (ownGeneration !== generation) return
    for (const url of objectUrls) URL.revokeObjectURL(url)
    objectUrls = []; opened = item
    draftKey = `opl-human:${snapshot.workspace_id}:${item.id}:v${item.viewed_revision}`
    const local = cached(draftKey)
    draft = local?.body ?? item.drafts.web.body
    pendingSend = local?.pendingSend ?? null
    draftVersion = item.drafts.web.version
    draftConflict = Boolean(local && item.drafts.web.body && local.body !== item.drafts.web.body)
    const detail = $('#detail'); detail.replaceChildren(); detail.hidden = false; $('#app').classList.add('detail-open')
    history.replaceState(null, '', `/?item=${item.id}&revision=${item.viewed_revision}`)
    detail.append(button('Back to inbox', () => {
      ++generation; clearTimeout(saveTimer); opened = null; detail.hidden = true; $('#app').classList.remove('detail-open'); history.replaceState(null, '', '/')
    }, 'back'))
    detail.append(el('div', `${item.id} · revision ${item.viewed_revision} · ${item.state.replace('_',' ')}`, 'detail-meta'), el('h1', item.title), el('p', item.summary, 'detail-summary'))
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
      versions.addEventListener('change', () => { void openItem(item.id, Number(versions.value)) })
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
            const response = await api(`/api/source?id=${item.id}&revision=${item.viewed_revision}&index=${index}${live ? '&live=1' : ''}`, null, true)
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
    const conversation = el('section', '', 'conversation'); conversation.append(el('h2', 'Conversation & outcomes'))
    if (!item.submissions.length) conversation.append(el('p', 'Ask a question, challenge the premise, or send a decision. A draft is not a submission.', 'muted'))
    for (const submission of item.submissions) {
      const human = el('div', '', 'message human')
      const queue = JSON.parse(submission.queue)
      human.append(el('div', `You · ${submission.kind} · v${submission.revision} · ${submission.state}${queue.state !== 'not_requested' ? ` · notification ${queue.state}` : ''}`, 'meta'), markdown(submission.body))
      conversation.append(human)
      const outcome = item.outcomes.find((candidate) => candidate.submission === submission.id)
      if (outcome) {
        const answer = el('div', '', 'message')
        answer.append(el('div', `Root · ${outcome.disposition.replace('_',' ')}`, 'meta'), markdown(outcome.text), el('p', `Source review: ${outcome.source_review}`, 'muted'))
        if (outcome.references.length) answer.append(markdown(outcome.references.map((ref) => `- ${ref}`).join('\n')))
        conversation.append(answer)
      }
    }
    detail.append(conversation)
    if (item.prepared) {
      const composer = el('section', '', 'composer')
      const caption = el('label', 'Your reply'); caption.htmlFor = 'reply'
      const input = el('textarea'); input.id = 'reply'; input.value = draft; input.placeholder = '“#6 combines two different responsibilities. Split them here…”'
      input.addEventListener('input', () => { draft = input.value; pendingSend = null; persist(); draftStatus('Draft saved on this device.'); clearTimeout(saveTimer); saveTimer = setTimeout(saveDraft, 700) })
      composer.append(caption, input)
      const actions = el('div', '', 'composer-actions'), select = el('select'); select.id = 'reply-kind'; select.setAttribute('aria-label', 'Reply type')
      for (const name of ['feedback','question']) { const option = el('option', name === 'feedback' ? 'Feedback / decision' : 'Question'); option.value = name; select.append(option) }
      if (pendingSend) select.value = pendingSend.kind
      actions.append(select, button('Save draft', saveDraft), button('Send', sendReply, 'primary')); actions.lastChild.id = 'send'
      const status = el('div', '', 'draft-status'); status.id = 'draft-status'; status.setAttribute('aria-live','polite')
      composer.append(actions, status)
      if (draftConflict) {
        composer.append(el('p', 'This device and the workspace have different drafts. Choose explicitly; neither has been overwritten.', 'warning'))
        composer.append(button('Keep this device draft', () => { draftConflict = false; void saveDraft() }), button('Use workspace draft', () => { draft = item.drafts.web.body; input.value = draft; pendingSend = null; draftConflict = false; persist(); draftStatus('Workspace draft loaded.') }))
      }
      detail.append(composer)
      draftStatus(draftConflict ? 'Draft conflict; choose which version to keep.' : draft ? 'Draft restored.' : 'Send submits explicitly. Saving does not instruct the agent.', draftConflict)
    }
    detail.append(el('p', `Published filesystem mtime_ns: ${item.published_mtime_ns} · observed: ${item.observed_mtime_ns}`, 'stamp'))
  } catch (error) { notice(error.message) }
}
function newContribution() {
  const key = `opl-human:${snapshot.workspace_id}:new`
  let local = cached(key) || {title: '', body: '', request_id: requestId()}
  const detail = $('#detail'); detail.replaceChildren(); detail.hidden = false
  opened = null; clearTimeout(saveTimer); $('#app').classList.add('detail-open')
  const title = el('input'); title.id = 'new-title'; title.value = local.title
  const body = el('textarea'); body.id = 'new-body'; body.value = local.body
  const titleLabel = el('label', 'Subject'); titleLabel.htmlFor = title.id
  const bodyLabel = el('label', 'Your contribution'); bodyLabel.htmlFor = body.id
  const store = () => {
    local = {title: title.value, body: body.value, request_id: requestId()}
    try { localStorage.setItem(key, JSON.stringify(local)) } catch { notice('Device storage is unavailable. Keep this page open until submitted.') }
  }
  title.addEventListener('input', store); body.addEventListener('input', store)
  const send = button('Send contribution', async () => {
    if (!title.value.trim() || !body.value.trim()) { notice('Add a subject and your contribution.'); return }
    send.disabled = true
    try {
      const receipt = await api('/api/contribute', local)
      localStorage.removeItem(key); snapshot = await api('/api/inbox'); renderQueue()
      await openItem(`H${String(receipt.item).padStart(3, '0')}`)
      notice('Your contribution is saved. The root owes you an outcome.')
    } catch (error) { notice(`Contribution retained for retry. ${error.message}`) }
    finally { send.disabled = false }
  }, 'primary')
  detail.append(button('Back to inbox', () => { detail.hidden = true; $('#app').classList.remove('detail-open') }, 'back'),
    el('h1', 'Start a contribution'), el('p', 'Raise a decision, challenge an assumption, or bring in something the agent has not asked about.'),
    titleLabel, title, bodyLabel, body, send)
}
$('#contribute').addEventListener('click', newContribution)
$('#refresh').addEventListener('click', refresh)
$('#pair-form').addEventListener('submit', async (event) => {
  event.preventDefault(); token = $('#token').value.trim(); sessionStorage.setItem('opl-human-token', token); await refresh()
})
await refresh()
const initial = new URLSearchParams(location.search)
if (snapshot && initial.has('item')) await openItem(initial.get('item'), Number(initial.get('revision')) || undefined)
