(function () {
  const html = document.documentElement;
  const themeToggle = document.getElementById('theme-toggle');
  const savedTheme = localStorage.getItem('roleta_theme');
  const initialTheme = savedTheme === 'dark' || savedTheme === 'light' ? savedTheme : 'dark';

  const updateThemeButton = (theme) => {
    if (!themeToggle) return;
    themeToggle.textContent = theme === 'dark' ? '\u2600\uFE0F' : '\u{1F319}';
    themeToggle.title = theme === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro';
    themeToggle.setAttribute('aria-label', themeToggle.title);
  };

  const applyTheme = (theme) => {
    html.setAttribute('data-theme', theme);
    localStorage.setItem('roleta_theme', theme);
    updateThemeButton(theme);
  };

  applyTheme(initialTheme);
  if (themeToggle) {
    themeToggle.addEventListener('click', () => {
      const current = html.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      applyTheme(current === 'dark' ? 'light' : 'dark');
    });
  }

  const giveawayId = window.ROULETTE_GIVEAWAY_ID;

  const copyButtons = Array.from(document.querySelectorAll('.js-copy-overlay'));
  copyButtons.forEach((copyButton) => {
    const targetId = copyButton.getAttribute('data-copy-target');
    const overlayUrl = targetId ? document.getElementById(targetId) : null;
    if (!overlayUrl) return;
    copyButton.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText((overlayUrl.textContent || '').trim());
        copyButton.textContent = 'Copiado!';
        setTimeout(() => {
          copyButton.textContent = 'Copiar URL';
        }, 1200);
      } catch {
        copyButton.textContent = 'Falhou ao copiar';
      }
    });
  });

  if (!giveawayId) return;

  const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${scheme}://${location.host}/ws/giveaways/${giveawayId}`);

  const count = document.getElementById('participants-count');
  const statusText = document.getElementById('status-text');
  const statusPill = document.getElementById('status-pill');
  const command = document.getElementById('command');
  const ticker = document.getElementById('ticker-name');
  const winnerCard = document.getElementById('winner-card');
  const lastWinner = document.getElementById('last-winner');
  const winnersList = document.getElementById('winners-list');
  const drawButton = document.getElementById('draw-button');
  const roulettePreviewFrame = document.getElementById('roulette-preview-frame');
  const rouletteWindow = document.getElementById('roulette-preview-window');
  const rouletteTrack = document.getElementById('roulette-preview-track');

  let lastCount = Number((count && count.textContent) || 0);
  const tickerDefault = (window.ROULETTE_TICKER_DEFAULT || 'Aguardando novas entradas...').trim();
  let tickerResetTimer = null;
  if (ticker && !ticker.textContent.trim()) {
    ticker.textContent = tickerDefault;
  }

  let lastWinnerKey = (lastWinner && lastWinner.textContent && lastWinner.textContent !== '-')
    ? `${lastWinner.textContent.trim()}|init`
    : null;

  let rouletteNames = [];
  let rouletteNamesKey = '';
  let rouletteCycleWidth = 1;
  let rouletteOffset = 0;
  let rouletteSpeed = 18;
  let roulettePhase = 'idle';
  let rouletteResolveAnim = null;
  let rouletteTs = performance.now();
  let plannedDraw = null;
  let drawLockUntil = 0;
  let deferredWinner = null;

  const easeOutCubic = (t) => 1 - Math.pow(1 - t, 3);

  const renderRouletteTrack = (names) => {
    if (!rouletteTrack) return;
    const safe = (names && names.length ? names : ['Aguardando', 'participantes']).slice(0, 500);
    rouletteNames = safe;
    rouletteNamesKey = safe.join('|');
    const cycle = safe
      .map((name, idx) => (`<span data-idx="${idx}" class="rounded-full border border-slate-200 bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-700">${name}</span>`))
      .join('');
    rouletteTrack.innerHTML = Array.from({ length: 8 }, () => cycle).join('');

    requestAnimationFrame(() => {
      let oneCycle = 0;
      for (let i = 0; i < safe.length; i += 1) {
        const chip = rouletteTrack.querySelector(`[data-idx="${i}"]`);
        if (!chip) continue;
        oneCycle = Math.max(oneCycle, chip.offsetLeft + chip.offsetWidth);
      }
      rouletteCycleWidth = Math.max(oneCycle + 8, 1);
      rouletteOffset = ((rouletteOffset % rouletteCycleWidth) + rouletteCycleWidth) % rouletteCycleWidth;
    });
  };

  const startRouletteSpin = () => {
    if (!rouletteTrack) return;
    if (roulettePhase === 'resolving') return;
    roulettePhase = 'spinning';
    rouletteSpeed = Math.max(rouletteSpeed, 240);
  };

  const resolveRouletteToWinner = (winnerName, durationMs = 1900) => {
    if (!rouletteTrack || !rouletteWindow || !winnerName) return;
    if (!rouletteNames.length) return;

    let winnerIdx = rouletteNames.findIndex((n) => n === winnerName);
    if (winnerIdx < 0) {
      rouletteNames = rouletteNames.concat([winnerName]);
      renderRouletteTrack(rouletteNames);
      winnerIdx = rouletteNames.length - 1;
    }

    const chip = rouletteTrack.querySelector(`[data-idx="${winnerIdx}"]`);
    if (!chip || rouletteCycleWidth <= 1) return;

    const chipCenter = chip.offsetLeft + chip.offsetWidth / 2;
    const markerX = rouletteWindow.clientWidth / 2;
    const currentMarkerGlobal = rouletteOffset + markerX;
    let targetGlobal = chipCenter;
    while (targetGlobal < currentMarkerGlobal + rouletteCycleWidth * 2.2) {
      targetGlobal += rouletteCycleWidth;
    }

    roulettePhase = 'resolving';
    rouletteResolveAnim = {
      startOffset: rouletteOffset,
      targetOffset: targetGlobal - markerX,
      startTs: performance.now(),
      durationMs,
    };
  };

  const startPlannedDraw = (winnerName, durationMs) => {
    if (!winnerName) return;
    const totalMs = Number.isFinite(durationMs) ? Math.max(3000, Math.min(5000, durationMs)) : 4200;
    const resolveMs = Math.min(2000, Math.floor(totalMs * 0.45));
    plannedDraw = {
      winnerName,
      totalMs,
      resolveMs,
      startedAt: performance.now(),
      resolved: false,
    };
    startRouletteSpin();
  };

  const animateRoulette = (ts) => {
    if (!rouletteTrack) return;
    const dt = Math.min((ts - rouletteTs) / 1000, 0.05);
    rouletteTs = ts;

    if (roulettePhase === 'spinning') {
      rouletteSpeed = Math.min(rouletteSpeed + 250 * dt, 420);
      rouletteOffset += rouletteSpeed * dt;

      if (plannedDraw && !plannedDraw.resolved) {
        const elapsed = ts - plannedDraw.startedAt;
        if (elapsed >= (plannedDraw.totalMs - plannedDraw.resolveMs)) {
          plannedDraw.resolved = true;
          resolveRouletteToWinner(plannedDraw.winnerName, plannedDraw.resolveMs);
        }
      }
    } else if (roulettePhase === 'resolving' && rouletteResolveAnim) {
      const t = Math.min((ts - rouletteResolveAnim.startTs) / rouletteResolveAnim.durationMs, 1);
      rouletteOffset = rouletteResolveAnim.startOffset
        + (rouletteResolveAnim.targetOffset - rouletteResolveAnim.startOffset) * easeOutCubic(t);
      if (t >= 1) {
        roulettePhase = 'idle';
        rouletteResolveAnim = null;
        rouletteSpeed = 18;
        plannedDraw = null;
      }
    } else {
      rouletteSpeed = 18;
      rouletteOffset += rouletteSpeed * dt;
    }

    if (rouletteCycleWidth > 1 && roulettePhase !== 'resolving') {
      rouletteOffset = ((rouletteOffset % rouletteCycleWidth) + rouletteCycleWidth) % rouletteCycleWidth;
    }
    rouletteTrack.style.transform = `translate(${-rouletteOffset}px, -50%)`;
    requestAnimationFrame(animateRoulette);
  };

  const setStatus = (open) => {
    if (statusText) statusText.textContent = open ? 'Aberto' : 'Fechado';
    if (statusPill) {
      statusPill.textContent = open ? 'SORTEIO ABERTO' : 'SORTEIO FECHADO';
      statusPill.className = open
        ? 'chip bg-emerald-100 text-emerald-700'
        : 'chip bg-slate-200 text-slate-700';
    }
  };

  const pushWinner = (winner) => {
    if (!winner) return;
    const winnerKey = `${winner.display_name}|${winner.platform}|${winner.drawn_at || ''}`;
    if (winnerKey === lastWinnerKey) return;

    if (lastWinner) lastWinner.textContent = winner.display_name;
    if (winnerCard) {
      winnerCard.classList.remove('winner-flash');
      void winnerCard.offsetWidth;
      winnerCard.classList.add('winner-flash');
    }

    if (winnersList) {
      const first = winnersList.firstElementChild;
      if (first && first.textContent && first.textContent.trim() === `${winner.display_name} (${winner.platform})`) {
        lastWinnerKey = winnerKey;
        return;
      }
      const item = document.createElement('li');
      item.className = 'text-sm border-b border-slate-100 pb-1';
      item.textContent = `${winner.display_name} (${winner.platform})`;
      winnersList.prepend(item);

      while (winnersList.children.length > 10) {
        winnersList.removeChild(winnersList.lastElementChild);
      }
    }
    lastWinnerKey = winnerKey;
  };

  const flushDeferredWinner = () => {
    if (!deferredWinner) return;
    if (performance.now() < drawLockUntil) return;
    pushWinner(deferredWinner);
    deferredWinner = null;
    if (drawButton) {
      drawButton.textContent = 'Sortear agora';
      drawButton.removeAttribute('disabled');
    }
  };

  ws.onmessage = async (event) => {
    const payload = JSON.parse(event.data);

    if (payload.type === 'draw_started') {
      const durationMs = Number(payload.duration_ms || 4200);
      deferredWinner = null;
      startPlannedDraw(payload.winner_name, durationMs);
      drawLockUntil = performance.now() + durationMs;
      setTimeout(flushDeferredWinner, Math.max(100, durationMs + 40));
      return;
    }

    const data = payload.type === 'state' ? payload.state : payload;
    if (!data) return;

    const currentCount = Number(data.participants_count || 0);

    if (count) count.textContent = String(currentCount);
    setStatus(Boolean(data.is_open));
    if (command) command.textContent = data.command || '!participar';

    if (currentCount > lastCount && ticker) {
      try {
        const resp = await fetch(`/giveaways/${giveawayId}/participants/latest`, { credentials: 'same-origin' });
        if (resp.ok) {
          const latest = await resp.json();
          if (latest.display_name) {
            ticker.textContent = `Novo participante no sorteio: ${latest.display_name}`;
            if (tickerResetTimer) {
              clearTimeout(tickerResetTimer);
            }
            tickerResetTimer = setTimeout(() => {
              ticker.textContent = tickerDefault;
            }, 4500);
          }
        }
      } catch {
        ticker.textContent = 'Participantes atualizados em tempo real.';
      }
    }

    if (data.last_winner) {
      if (performance.now() < drawLockUntil) {
        deferredWinner = data.last_winner;
        setTimeout(flushDeferredWinner, Math.max(80, drawLockUntil - performance.now() + 20));
      } else {
        pushWinner(data.last_winner);
        if (drawButton) {
          drawButton.textContent = 'Sortear agora';
          drawButton.removeAttribute('disabled');
        }
      }
    }

    const names = Array.isArray(data.participant_names) ? data.participant_names : [];
    const namesKey = names.join('|');
    if (rouletteTrack && namesKey !== rouletteNamesKey) {
      renderRouletteTrack(names);
    }

    lastCount = currentCount;
  };

  if (drawButton && drawButton.form) {
    drawButton.form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      if (drawButton.hasAttribute('disabled')) return;
      drawButton.textContent = 'Sorteando...';
      drawButton.setAttribute('disabled', 'disabled');
      if (roulettePreviewFrame && roulettePreviewFrame.contentWindow) {
        roulettePreviewFrame.contentWindow.postMessage({ type: 'preview_draw_started' }, location.origin);
      }
      try {
        const resp = await fetch(drawButton.form.action, {
          method: 'POST',
          body: new FormData(drawButton.form),
          credentials: 'same-origin',
          headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (!resp.ok) {
          let message = 'Nao foi possivel sortear agora.';
          try {
            const payload = await resp.json();
            if (payload && payload.detail) message = String(payload.detail);
          } catch (_) {
          }
          drawButton.textContent = 'Sortear agora';
          drawButton.removeAttribute('disabled');
          alert(message);
          return;
        }
        setTimeout(() => {
          if (drawButton.hasAttribute('disabled')) {
            drawButton.textContent = 'Sortear agora';
            drawButton.removeAttribute('disabled');
          }
        }, 8000);
      } catch (_) {
        drawButton.textContent = 'Sortear agora';
        drawButton.removeAttribute('disabled');
        alert('Falha de conexao ao tentar sortear.');
      }
    });
  }

  if (rouletteTrack) {
    renderRouletteTrack([]);
    requestAnimationFrame(animateRoulette);
  }
})();
