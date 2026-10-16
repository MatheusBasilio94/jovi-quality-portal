export default function(component) {
  const {data, parentElement, setTriggerValue} = component;
  const root = parentElement.querySelector('.kanban-root');
  root.replaceChildren();
  root.classList.remove('busy');
  let dragging = null;
  let busy = false;
  const zones = [];
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if(cls) node.className = cls;
    if(text !== undefined) node.textContent = text;
    return node;
  };
  const feedback = make('div', 'kanban-feedback');
  feedback.setAttribute('role', 'status');
  feedback.setAttribute('aria-live', 'polite');
  const grid = make('div', 'kanban-grid');
  root.append(feedback, grid);
  const send = event => {
    if(busy) return;
    busy = true;
    root.classList.add('busy');
    feedback.textContent = event.kind === 'move' ? 'Saving status…' : 'Opening action…';
    setTriggerValue('event', {...event, token: crypto.randomUUID()});
  };
  const move = (card, status) => {
    if(!data.movable || card.status === status) return;
    send({kind:'move', id:card.id, revision:card.revision, status});
  };
  const themes = [['#2563EB','#E3EDFF'],['#7752D9','#ECE6FF'],['#B77909','#FFF3D7'],['#07854B','#DCF5E8']];
  data.statuses.forEach((status, index) => {
    const zone = make('section','kanban-lane');
    zone.dataset.status = status;
    zone.setAttribute('aria-label', status+' actions');
    zone.style.setProperty('--tone', themes[index][0]);
    zone.style.setProperty('--wash', themes[index][1]);
    const cards = data.cards.filter(card => card.status === status);
    const header = make('div','kanban-heading',status);
    header.append(make('span','kanban-count',String(cards.length)));
    zone.append(header);
    zones.push(zone);
    zone.addEventListener('dragover', event => {
      if(!data.movable || !dragging || busy) return;
      event.preventDefault();
      event.dataTransfer.dropEffect = 'move';
      zone.classList.add('drop-target');
    });
    zone.addEventListener('dragleave', event => {
      if(!zone.contains(event.relatedTarget)) zone.classList.remove('drop-target');
    });
    zone.addEventListener('drop', event => {
      event.preventDefault();
      zones.forEach(node => node.classList.remove('drop-target'));
      if(dragging) move(dragging, status);
    });
    cards.forEach(card => {
      const article = make('article','action-card');
      article.dataset.actionId = card.id;
      article.draggable = !!data.movable;
      article.setAttribute('aria-label',card.title);
      article.addEventListener('dragstart',event => {
        if(!data.movable || busy){event.preventDefault();return;}
        dragging = card;
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain',card.id);
        article.classList.add('dragging');
      });
      article.addEventListener('dragend',() => {
        dragging = null;
        article.classList.remove('dragging');
        zones.forEach(node => node.classList.remove('drop-target'));
      });
      const tags = make('div','action-tags');
      tags.append(make('span','action-tag',card.area),make('span','priority '+card.priority.toLowerCase(),card.priority+' priority'));
      if(data.movable){
        const grip = make('span','drag-grip','⠿');
        grip.title = 'Drag this card to another status';
        tags.append(grip);
      }
      const owner = make('div','action-owner');
      owner.append(make('span','owner-circle',(card.owner || '?').slice(0,1).toUpperCase()),make('span','',card.owner));
      const open = make('button','open-action','Open action ↗');
      open.type = 'button';
      open.addEventListener('click',() => send({kind:'open', id:card.id}));
      article.append(tags,make('div','action-title',card.title),make('div','action-model',(card.model || 'All models')+' · '+(card.code || card.id)),
                     owner,make('div','action-due '+card.due_kind,card.due_label),open);
      if(data.movable){
        const select = make('select','move-action');
        select.setAttribute('aria-label','Move '+card.title+' to status');
        const placeholder = make('option','','Move to…');
        placeholder.value = '';
        select.append(placeholder);
        data.statuses.forEach(target => {
          const option = make('option','',target);
          option.value = target;
          option.disabled = target === card.status;
          select.append(option);
        });
        select.addEventListener('change',() => move(card,select.value));
        article.append(select);
      }
      zone.append(article);
    });
    if(!cards.length) zone.append(make('p','empty-lane','No actions in this status.'));
    const add = make('button','add-action','＋ Add action');
    add.type = 'button';
    add.disabled = !data.editable;
    add.addEventListener('click',() => send({kind:'new',status}));
    zone.append(add);
    grid.append(zone);
  });
}
