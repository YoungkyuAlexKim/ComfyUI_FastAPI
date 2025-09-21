// Prompt tag weighting with Ctrl+Arrow keys
// - Ctrl+ArrowUp: increase weight
// - Ctrl+ArrowDown: decrease weight
// Supports: cursor token, multi-selection range (comma-separated tags)
// IIFE to avoid globals; respects Prettier and existing style
(function () {
  function clamp(value, min, max) {
    return Math.max(min, Math.min(max, value));
  }

  function formatWeight(w, precision) {
    const p = Number.isFinite(precision) ? precision : 2;
    return parseFloat(Number(w).toFixed(p));
  }

  function getConfig() {
    const cfg = (window.APP_CONFIG && window.APP_CONFIG.weight) || {};
    const step = Number.isFinite(cfg.step) ? cfg.step : 0.1;
    const shiftMultiplier = Number.isFinite(cfg.shiftMultiplier)
      ? cfg.shiftMultiplier
      : 2;
    const min = Number.isFinite(cfg.min) ? cfg.min : 0.1;
    const max = Number.isFinite(cfg.max) ? cfg.max : 3.0;
    const precision = Number.isFinite(cfg.precision) ? cfg.precision : 2;
    return { step, shiftMultiplier, min, max, precision };
  }

  // Parse a single tag possibly with weight syntax like:
  //  - tag
  //  - tag:1.2 (A1111 style)
  //  - (tag:1.2) (emphasis syntax)
  // Returns { core:"tag", weight:number|null, wrapper:"paren"|"plain" }
  function parseWeightedTag(raw) {
    const s = raw.trim();
    if (!s) return { core: '', weight: null, wrapper: 'plain' };
    // (tag:1.2)
    const mParen = s.match(/^\(([^:()]+)\s*:(\s*[-+]?[0-9]*\.?[0-9]+)\)$/);
    if (mParen) {
      return {
        core: mParen[1].trim(),
        weight: parseFloat(mParen[2]),
        wrapper: 'paren',
      };
    }
    // tag:1.2
    const mPlain = s.match(/^([^:(),]+)\s*:(\s*[-+]?[0-9]*\.?[0-9]+)$/);
    if (mPlain) {
      return { core: mPlain[1].trim(), weight: parseFloat(mPlain[2]), wrapper: 'plain' };
    }
    // plain tag (no explicit weight)
    return { core: s, weight: null, wrapper: 'plain' };
  }

  // Render single token with desired weight (normalized: always use paren style when weight != 1)
  function renderSingleWeighted(core, weight, precision) {
    const w = formatWeight(weight, precision);
    if (w === 1) return core;
    return `(${core}:${w})`;
  }

  // Tokenize a selection by commas, preserving separators for rejoin
  function splitTagsPreserving(text) {
    const parts = [];
    let start = 0;
    for (let i = 0; i < text.length; i++) {
      const ch = text[i];
      if (ch === ',') {
        parts.push({ type: 'token', text: text.slice(start, i) });
        parts.push({ type: 'sep', text: ',' });
        start = i + 1;
      }
    }
    parts.push({ type: 'token', text: text.slice(start) });
    return parts;
  }

  function joinParts(parts) {
    return parts.map((p) => p.text).join('');
  }

  // Determine the token boundaries around a given caret offset
  function findTokenBoundsAround(text, offset) {
    let left = offset;
    while (left > 0 && text[left - 1] !== ',') left--;
    let right = offset;
    while (right < text.length && text[right] !== ',') right++;
    // Trim surrounding spaces
    const leading = /^\s*/.exec(text.slice(left, right))[0].length;
    const trailing = /\s*$/.exec(text.slice(left, right))[0].length;
    return { start: left + leading, end: right - trailing };
  }

  // Adjust weight for a selection. If multiple tags selected (contains comma), treat as one group.
  function adjustWeightOnRange(text, selStart, selEnd, delta) {
    const range = text.slice(selStart, selEnd);
    if (/,/.test(range)) {
      return adjustGroupWeight(text, selStart, selEnd, delta);
    }
    // Fallback: adjust token(s) within selection individually
    const { min, max, precision } = getConfig();
    const parts = splitTagsPreserving(range);
    for (const p of parts) {
      if (p.type !== 'token') continue;
      const tag = parseWeightedTag(p.text);
      if (!tag.core) continue;
      const current = Number.isFinite(tag.weight) ? tag.weight : 1.0;
      const next = clamp(current + delta, min, max);
      p.text = renderSingleWeighted(tag.core, next, precision);
    }
    return text.slice(0, selStart) + joinParts(parts) + text.slice(selEnd);
  }

  function adjustGroupWeight(text, selStart, selEnd, delta) {
    const { min, max, precision } = getConfig();
    const range = text.slice(selStart, selEnd);
    const lead = /^\s*/.exec(range)[0];
    const trail = /\s*$/.exec(range)[0];
    const core = range.slice(lead.length, range.length - trail.length);
    const m = core.match(/^\(([^]*?)\s*:\s*([-+]?[0-9]*\.?[0-9]+)\)$/);
    let inner = core;
    let current = 1.0;
    if (m) {
      inner = m[1];
      const parsed = parseFloat(m[2]);
      if (Number.isFinite(parsed)) current = parsed;
    }
    const next = clamp(current + delta, min, max);
    const rounded = formatWeight(next, precision);
    const replaced = rounded === 1
      ? inner
      : `(${inner}:${rounded})`;
    return text.slice(0, selStart) + lead + replaced + trail + text.slice(selEnd);
  }

  function adjustWeightAtCaret(text, caret, delta) {
    const { min, max, precision } = getConfig();

    // 1) Prefer adjusting an enclosing weighted group that contains multiple tags
    const groups = findEnclosingWeightedGroups(text, caret);
    if (groups.length) {
      // Choose the outermost group that looks like a multi-tag group (contains comma)
      let groupToAdjust = null;
      for (let k = 0; k < groups.length; k++) {
        if (groups[k].content.indexOf(',') !== -1) {
          groupToAdjust = groups[k];
          break;
        }
      }
      // If none contains comma, adjust the innermost group (single weighted token)
      if (!groupToAdjust) groupToAdjust = groups[groups.length - 1];

      const current = Number.isFinite(groupToAdjust.weight)
        ? groupToAdjust.weight
        : 1.0;
      const next = clamp(current + delta, min, max);
      const rounded = formatWeight(next, precision);
      const replacement = rounded === 1
        ? groupToAdjust.content
        : `(${groupToAdjust.content}:${rounded})`;
      return (
        text.slice(0, groupToAdjust.start) +
        replacement +
        text.slice(groupToAdjust.end)
      );
    }

    // 2) Fallback to token-level weighting at caret
    const bounds = findTokenBoundsAround(text, caret);
    const token = text.slice(bounds.start, bounds.end);
    const tag = parseWeightedTag(token);
    if (!tag.core) return null;
    const current = Number.isFinite(tag.weight) ? tag.weight : 1.0;
    const next = clamp(current + delta, min, max);
    const replaced = renderSingleWeighted(tag.core, next, precision);
    return text.slice(0, bounds.start) + replaced + text.slice(bounds.end);
  }

  // Find all enclosing weighted groups (outermost → innermost) around caret
  function findEnclosingWeightedGroups(text, caret) {
    const groups = [];
    // Scan left for '(' candidates and check matching ')' that encloses caret
    for (let i = caret; i >= 0; i--) {
      if (text[i] !== '(') continue;
      let depth = 0;
      let end = -1;
      for (let j = i; j < text.length; j++) {
        const ch = text[j];
        if (ch === '(') depth++;
        else if (ch === ')') {
          depth--;
          if (depth === 0) {
            end = j + 1; // exclusive
            break;
          }
        }
      }
      if (end === -1) break; // unmatched
      if (i <= caret && end >= caret) {
        const inner = text.slice(i + 1, end - 1);
        const lastColon = inner.lastIndexOf(':');
        if (lastColon !== -1) {
          const weightStr = inner.slice(lastColon + 1).trim();
          if (/^[-+]?\d*\.?\d+$/.test(weightStr)) {
            const content = inner.slice(0, lastColon);
            const weight = parseFloat(weightStr);
            groups.push({ start: i, end, content, weight });
          }
        }
      }
    }
    // Order outermost → innermost by ascending start
    groups.sort((a, b) => a.start - b.start);
    return groups;
  }

  function computeDelta(evt) {
    const { step, shiftMultiplier } = getConfig();
    const base = evt.key === 'ArrowUp' ? step : -step;
    return evt.shiftKey ? base * shiftMultiplier : base;
  }

  function handleKeyDown(e) {
    if (!(e.ctrlKey || e.metaKey)) return;
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;
    const ta = e.target;
    if (!(ta && ta.tagName === 'TEXTAREA' && ta.id === 'user_prompt')) return;
    e.preventDefault();
    const delta = computeDelta(e);
    const text = ta.value || '';
    const selStart = ta.selectionStart || 0;
    const selEnd = ta.selectionEnd || selStart;

    let nextText = null;
    if (selEnd > selStart) {
      nextText = adjustWeightOnRange(text, selStart, selEnd, delta);
    } else {
      nextText = adjustWeightAtCaret(text, selStart, delta);
    }
    if (typeof nextText === 'string' && nextText !== text) {
      const prevScroll = ta.scrollTop;
      ta.value = nextText;
      try {
        ta.dispatchEvent(new Event('input'));
      } catch (_) {}
      // Keep caret reasonably near the change; set to start of affected block
      if (selEnd > selStart) {
        ta.selectionStart = selStart;
        ta.selectionEnd = selStart;
      } else {
        ta.selectionStart = ta.selectionEnd = selStart;
      }
      ta.scrollTop = prevScroll;
    }
  }

  document.addEventListener('keydown', handleKeyDown);
})();


