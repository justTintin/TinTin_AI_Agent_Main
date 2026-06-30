import React from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, spring} from 'remotion';

const FONT = 'system-ui, "PingFang SC", "Microsoft YaHei", sans-serif';

// ── 动态标题：标题上滑+淡入，副标题随后 ──────────────────────────
export const TitleReveal: React.FC<{title: string; subtitle: string; bg: string; color: string}> = ({
  title, subtitle, bg, color,
}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const s = spring({frame, fps, config: {damping: 200}});
  const y = interpolate(s, [0, 1], [60, 0]);
  const op = interpolate(frame, [0, 12], [0, 1], {extrapolateRight: 'clamp'});
  const subOp = interpolate(frame, [14, 28], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return (
    <AbsoluteFill style={{backgroundColor: bg, justifyContent: 'center', alignItems: 'center', fontFamily: FONT}}>
      <div style={{transform: `translateY(${y}px)`, opacity: op, color, fontSize: 110, fontWeight: 800, textAlign: 'center', padding: '0 80px'}}>
        {title}
      </div>
      <div style={{color, fontSize: 52, marginTop: 24, opacity: subOp * 0.85}}>
        {subtitle}
      </div>
    </AbsoluteFill>
  );
};

// ── 逐字弹出字幕：每个字符依次 spring 入场 ──────────────────────
export const KineticSubtitle: React.FC<{text: string; color: string; bg: string}> = ({text, color, bg}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const chars = Array.from(text || '');
  return (
    <AbsoluteFill style={{backgroundColor: bg, justifyContent: 'center', alignItems: 'center', fontFamily: FONT}}>
      <div style={{display: 'flex', flexWrap: 'wrap', justifyContent: 'center', maxWidth: 900}}>
        {chars.map((ch, i) => {
          const s = spring({frame: frame - i * 2, fps, config: {damping: 12, stiffness: 120}});
          return (
            <span key={i} style={{color, fontSize: 86, fontWeight: 800, opacity: s, transform: `scale(${0.4 + s * 0.6})`, display: 'inline-block'}}>
              {ch === ' ' ? ' ' : ch}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

// ── 数字增长：from → to 滚动 ────────────────────────────────
export const NumberCounter: React.FC<{label: string; from: number; to: number; suffix: string; color: string; bg: string}> = ({
  label, from, to, suffix, color, bg,
}) => {
  const frame = useCurrentFrame();
  const {durationInFrames} = useVideoConfig();
  const p = interpolate(frame, [0, durationInFrames - 15], [0, 1], {extrapolateRight: 'clamp'});
  const val = Math.round(interpolate(p, [0, 1], [from, to]));
  return (
    <AbsoluteFill style={{backgroundColor: bg, justifyContent: 'center', alignItems: 'center', fontFamily: FONT}}>
      <div style={{color, opacity: 0.8, fontSize: 56, marginBottom: 16}}>{label}</div>
      <div style={{color, fontSize: 180, fontWeight: 900, fontVariantNumeric: 'tabular-nums'}}>
        {val.toLocaleString()}{suffix}
      </div>
    </AbsoluteFill>
  );
};

// ── 下三分之一字幕条：底部滑入的标签条 ──────────────────────────
export const LowerThird: React.FC<{title: string; subtitle: string; color: string; accent: string}> = ({
  title, subtitle, color, accent,
}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const s = spring({frame, fps, config: {damping: 200}});
  const x = interpolate(s, [0, 1], [-width, 0]);
  return (
    <AbsoluteFill style={{justifyContent: 'flex-end', fontFamily: FONT, paddingBottom: 360}}>
      <div style={{transform: `translateX(${x}px)`, marginLeft: 80, maxWidth: 820}}>
        <div style={{display: 'inline-block', background: accent, color, fontSize: 64, fontWeight: 800, padding: '14px 28px', borderRadius: 8}}>
          {title}
        </div>
        <div style={{marginTop: 14, background: 'rgba(0,0,0,0.6)', color, fontSize: 40, padding: '10px 22px', borderRadius: 6, display: 'inline-block'}}>
          {subtitle}
        </div>
      </div>
    </AbsoluteFill>
  );
};
