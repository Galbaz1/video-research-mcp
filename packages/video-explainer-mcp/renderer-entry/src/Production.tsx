import React from 'react';
import {AbsoluteFill, Audio, Sequence, staticFile} from 'remotion';
import {sceneRegistry} from '@project-scenes';
import type {ProductionProps} from '@project-scenes';

export const Production: React.FC<ProductionProps> = ({scenes}) => (
  <AbsoluteFill>
    {scenes.map((scene) => {
      if (!Object.prototype.hasOwnProperty.call(sceneRegistry, scene.type) || !sceneRegistry[scene.type]) {
        throw new Error(`Missing project sceneRegistry type: ${scene.type}`);
      }
      const Scene = sceneRegistry[scene.type];
      return (
        <Sequence key={scene.id} from={scene.from} durationInFrames={scene.durationInFrames} name={scene.title}>
          <Scene scene={scene} />
          <Sequence durationInFrames={scene.audioDurationInFrames} layout="none">
            <Audio src={staticFile(scene.audio_src)} />
          </Sequence>
        </Sequence>
      );
    })}
  </AbsoluteFill>
);
