(function(){
  /**
   * Task Explorer Script
   * Fixes: Rubric modal previously appeared empty because children were collapsed and fetch path could 404.
   * Changes: Expand rubric tree by default, improve fetch base path resolution, add console diagnostics, and focus management for accessibility.
   */
  const TASKS_URL = (window.__TASKS_URL__) || (document.location.origin + (document.querySelector('html').getAttribute('data-baseurl')||'') + '/task_registry/tasks.json');
  // Fallback simpler relative path
  const RELATIVE_URL = '/task_registry/tasks.json';

  const tasksListEl = document.getElementById('tasks-list');
  const statsEl = document.getElementById('task-stats');
  const applyBtn = document.getElementById('apply-filters');
  const resetBtn = document.getElementById('reset-filters');
  const diffCheckboxes = Array.from(document.querySelectorAll('.diff-filter'));
  const searchIdEl = document.getElementById('search-id');
  const searchTextEl = document.getElementById('search-text');
  const limitCountEl = document.getElementById('limit-count');

  const rubricModal = document.getElementById('rubric-modal');
  const rubricClose = document.getElementById('rubric-close');
  const rubricTreeEl = document.getElementById('rubric-tree');
  const rubricTitleEl = document.getElementById('rubric-title');

  let TASKS = {};

  async function loadTasks(){
    let url = RELATIVE_URL; // use relative for GH Pages
    try {
      const res = await fetch(url);
      if(!res.ok) throw new Error('Failed to fetch tasks.json');
      TASKS = await res.json();
      render();
    } catch (e){
      tasksListEl.innerHTML = `<div class="error">Error loading tasks: ${e.message}</div>`;
    }
  }

  function getFilters(){
    const diffs = diffCheckboxes.filter(cb=>cb.checked).map(cb=>cb.value);
    const idQuery = searchIdEl.value.trim().toLowerCase();
    const textQuery = searchTextEl.value.trim().toLowerCase();
    const limit = parseInt(limitCountEl.value,10) || 50;
    return {diffs,idQuery,textQuery,limit};
  }

  function filterTasks(){
    const {diffs,idQuery,textQuery,limit} = getFilters();
    const entries = Object.entries(TASKS);
    let filtered = entries.filter(([id,data])=>{
      const diff = (data.misc && data.misc.difficulty) || 'Unknown';
      if(!diffs.includes(diff)) return false;
      if(idQuery && !id.toLowerCase().includes(idQuery)) return false;
      if(textQuery){
        const goal = (data.goal||'').toLowerCase();
        if(!goal.includes(textQuery)) return false;
      }
      return true;
    });
    return filtered.slice(0, limit);
  }

  function renderStats(allCount, shown){
    const difficultyCounts = {};
    Object.values(TASKS).forEach(t=>{
      const d = (t.misc && t.misc.difficulty) || 'Unknown';
      difficultyCounts[d] = (difficultyCounts[d]||0)+1;
    });
    // Add difficulty-specific classes so we can colorize the labels consistently with badges
    const parts = Object.entries(difficultyCounts).map(([d,c])=>{
      const cls = `stat-item diff-${d.toLowerCase()}`; // e.g. diff-hard / diff-easy / diff-medium
      return `<span class="${cls}"><strong>${d}:</strong> ${c}</span>`;
    }).join('');
    statsEl.innerHTML = `<div class="stats-bar"><span><strong>Total Tasks:</strong> ${allCount}</span>${parts}<span><strong>Showing:</strong> ${shown}</span></div>`;
  }

  function render(){
    const allCount = Object.keys(TASKS).length;
    const filtered = filterTasks();
    renderStats(allCount, filtered.length);
    if(!filtered.length){
      tasksListEl.innerHTML = '<div class="empty">No tasks match filters.</div>';
      return;
    }
    const html = filtered.map(([id,data])=>{
      const diff = (data.misc && data.misc.difficulty) || 'Unknown';
      const goal = data.goal || '';
      const rubricPath = data.rubric_path || '';
      return `<div class="task-card diff-${diff.toLowerCase()}">
        <div class="task-header">
          <span class="task-id">${id}</span>
          <span class="task-diff badge badge-${diff.toLowerCase()}">${diff}</span>
        </div>
        <div class="task-goal">${escapeHtml(goal)}</div>
        <div class="task-actions">
          <button class="btn btn-sm btn-secondary" data-rubric="${rubricPath}" data-taskid="${id}">View Rubric</button>
        </div>
      </div>`;
    }).join('');
    tasksListEl.innerHTML = html;
  }

  function escapeHtml(str){
    return str.replace(/[&<>]/g, s=>({ '&':'&amp;','<':'&lt;','>':'&gt;' }[s]));
  }
  function escapeAttr(str){
    return str.replace(/"/g,'&quot;');
  }

  function resolveRubricUrl(rubricPath){
    // Support sites served under a baseurl (even if baseurl currently empty)
    const base = document.querySelector('html').getAttribute('data-baseurl') || '';
    // Ensure no double slashes
    return `${base}/${rubricPath}`.replace(/\/+/, '/');
  }

  async function openRubric(rubricPath, taskId){
    rubricTreeEl.innerHTML = '<div class="loading">Loading rubric...</div>';
    rubricTitleEl.textContent = `Rubric: ${taskId}`;
    rubricModal.hidden = false;
    try {
      const url = resolveRubricUrl(rubricPath.replace(/^\//,''));
      console.debug('[TaskExplorer] Fetching rubric:', url);
      const res = await fetch(url);
      if(!res.ok) throw new Error('Failed to fetch rubric');
      const data = await res.json();
      if(!data || !data.root){
        throw new Error('Malformed rubric JSON: missing root');
      }
      rubricTreeEl.innerHTML = renderRubricNode(data.root, 0, true);
      attachToggleHandlers();
      trapFocus(rubricModal);
    } catch(e){
      rubricTreeEl.innerHTML = `<div class="error">${e.message}</div>`;
      console.error('[TaskExplorer] Rubric load error:', e);
    }
  }

  function renderRubricNode(node, depth = 0, expandAll = false){
    if(!node) return '<div class="error">Invalid rubric node</div>';
    const childrenRaw = node.children || [];
    const hasChildren = childrenRaw.length > 0;
    // By default only depth 0 expanded unless expandAll
    const expanded = expandAll || depth === 0;
    const childrenMarkup = hasChildren ? childrenRaw.map(child => renderRubricNode(child, depth+1, expandAll)).join('') : '';
    const scorer = node.scorer ? `<pre class="scorer-code" hidden><code class="language-python">${escapeHtml(node.scorer.function_code||'')}</code></pre>` : '';
    const codeBtn = node.scorer ? '<button class="btn btn-xs toggle-code" aria-label="Toggle code">Code</button>' : '';
    const toggleChildrenBtn = hasChildren ? `<button class="btn btn-xs toggle-children" aria-label="Toggle children">${expanded? 'Hide' : 'Show'}</button>` : '';
    const indentStyle = depth > 0 ? `style=\"margin-left:${depth*16}px\"` : '';
    return `<div class="rubric-node ${node.is_critical?'critical':''}" data-depth="${depth}" ${indentStyle}>
      <div class="rubric-node-header">
        <span class="rubric-node-title">${escapeHtml(node.name||'Unnamed')}</span>
        <span class="rubric-node-tags">${node.is_critical?'<span class="tag critical-tag">Critical</span>':''}</span>
        ${codeBtn}
        ${toggleChildrenBtn}
      </div>
      <div class="rubric-node-desc">${escapeHtml(node.description||'')}</div>
      ${scorer}
      ${hasChildren?`<div class="rubric-children" ${expanded?'':'hidden'}>${childrenMarkup}</div>`:''}
    </div>`;
  }

  function attachToggleHandlers(){
    rubricTreeEl.querySelectorAll('.toggle-children').forEach(btn=>{
      btn.addEventListener('click',()=>{
        const nodeEl = btn.closest('.rubric-node');
        if(!nodeEl) return;
        const isCollapsed = nodeEl.classList.toggle('collapsed');
        // Update button text
        btn.textContent = isCollapsed ? 'Show' : 'Hide';
      });
    });
    rubricTreeEl.querySelectorAll('.toggle-code').forEach(btn=>{
      btn.addEventListener('click',()=>{
        const code = btn.parentElement.parentElement.querySelector('.scorer-code');
        if(!code) return;
        code.hidden = !code.hidden;
        btn.textContent = code.hidden ? 'Code' : 'Hide Code';
        btn.classList.toggle('active', !code.hidden);
        // Apply Prism syntax highlighting when code is revealed
        if(!code.hidden && typeof Prism !== 'undefined'){
          Prism.highlightAllUnder(code);
        }
      });
    });
  }

  // Expand / Collapse All controls
  const expandAllBtn = document.getElementById('expand-all');
  const collapseAllBtn = document.getElementById('collapse-all');
  if(expandAllBtn) {
    expandAllBtn.addEventListener('click', ()=>{
      rubricTreeEl.querySelectorAll('.rubric-node.collapsed').forEach(n=>n.classList.remove('collapsed'));
      rubricTreeEl.querySelectorAll('.toggle-children').forEach(btn=>{ btn.textContent = 'Hide'; });
    });
  }
  if(collapseAllBtn) {
    collapseAllBtn.addEventListener('click', ()=>{
      rubricTreeEl.querySelectorAll('.rubric-node').forEach(node=>{
        const depth = parseInt(node.getAttribute('data-depth'),10);
        const btn = node.querySelector('.toggle-children');
        if(depth === 0) {
          node.classList.remove('collapsed');
          if(btn) btn.textContent = 'Hide';
        } else {
          node.classList.add('collapsed');
          if(btn) btn.textContent = 'Show';
        }
      });
    });
  }

  applyBtn.addEventListener('click', render);
  resetBtn.addEventListener('click', ()=>{
    diffCheckboxes.forEach(cb=>cb.checked=true);
    searchIdEl.value='';
    searchTextEl.value='';
    limitCountEl.value='50';
    render();
  });

  tasksListEl.addEventListener('click', e=>{
    const rubricBtn = e.target.closest('button[data-rubric]');
    if(rubricBtn){
      openRubric(rubricBtn.dataset.rubric, rubricBtn.dataset.taskid);
      return;
    }
  });

  rubricClose.addEventListener('click', closeRubricModal);
  function closeRubricModal(){ rubricModal.hidden = true; rubricTreeEl.innerHTML=''; releaseFocusTrap(); }
  window.addEventListener('keydown', e=>{ if(e.key==='Escape' && !rubricModal.hidden){ rubricModal.hidden = true; }});

  // Simple focus trap for modal accessibility
  let lastFocusedElement = null;
  function trapFocus(modal){
    lastFocusedElement = document.activeElement;
    const focusable = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    if(focusable.length){ focusable[0].focus(); }
    function handleTab(e){
      if(e.key !== 'Tab') return;
      const list = Array.from(focusable).filter(el=>!el.disabled && el.offsetParent !== null);
      if(!list.length) return;
      const first = list[0];
      const last = list[list.length-1];
      if(e.shiftKey){
        if(document.activeElement === first){ e.preventDefault(); last.focus(); }
      } else {
        if(document.activeElement === last){ e.preventDefault(); first.focus(); }
      }
    }
    modal.addEventListener('keydown', handleTab);
    modal.__trapHandler = handleTab;
  }
  function releaseFocusTrap(){
    if(lastFocusedElement){ lastFocusedElement.focus(); }
    if(rubricModal.__trapHandler){ rubricModal.removeEventListener('keydown', rubricModal.__trapHandler); delete rubricModal.__trapHandler; }
  }

  loadTasks();
})();
