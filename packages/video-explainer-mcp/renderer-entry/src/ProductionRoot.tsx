import React from 'react';
import {Composition} from 'remotion';
import {Production} from './Production';
import type {ProductionProps} from '@project-scenes';

const defaultProps: ProductionProps = {
  width: 1280, height: 720, fps: 30, durationInFrames: 1, scenes: [],
};

export const ProductionRoot: React.FC = () => (
  <Composition
    id="Production"
    component={Production}
    defaultProps={defaultProps}
    calculateMetadata={({props}) => {
      if (props.fps !== 30 || props.scenes.length === 0) {
        throw new Error('Production requires admitted scenes at 30 FPS');
      }
      return {
        width: props.width, height: props.height, fps: props.fps,
        durationInFrames: props.durationInFrames,
      };
    }}
  />
);
