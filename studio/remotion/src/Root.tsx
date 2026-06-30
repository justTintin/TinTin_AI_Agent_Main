import React from 'react';
import {Composition} from 'remotion';
import {TitleReveal, KineticSubtitle, NumberCounter, LowerThird} from './Templates';

// 统一画布：1080x1920（9:16），30fps，3 秒（90 帧）。
const W = 1080;
const H = 1920;
const FPS = 30;
const DUR = 90;

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="TitleReveal"
        component={TitleReveal as any}
        durationInFrames={DUR}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={{title: '主标题', subtitle: '副标题', bg: '#101418', color: '#FFFFFF'}}
      />
      <Composition
        id="KineticSubtitle"
        component={KineticSubtitle as any}
        durationInFrames={DUR}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={{text: '逐字弹出的字幕文案', color: '#FFFFFF', bg: '#101418'}}
      />
      <Composition
        id="NumberCounter"
        component={NumberCounter as any}
        durationInFrames={DUR}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={{label: '累计销量', from: 0, to: 9999, suffix: '+', color: '#FFD54A', bg: '#101418'}}
      />
      <Composition
        id="LowerThird"
        component={LowerThird as any}
        durationInFrames={DUR}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={{title: '产品名称', subtitle: '一句话卖点', color: '#FFFFFF', accent: '#FF3366'}}
      />
    </>
  );
};
