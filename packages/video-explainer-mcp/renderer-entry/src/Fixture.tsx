import React from 'react';
import {AbsoluteFill, Audio, staticFile} from 'remotion';

export type FixtureProps = {
  color: string;
  audio_file: string;
  audio_duration_seconds: number;
};

export const Fixture: React.FC<FixtureProps> = ({color, audio_file}) => (
  <AbsoluteFill style={{backgroundColor: color}}>
    <Audio src={staticFile(audio_file)} />
  </AbsoluteFill>
);
