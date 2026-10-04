import React from 'react';
import {Composition} from 'remotion';
import {Fixture} from './Fixture';

export const Root: React.FC = () => (
  <Composition
    id="Fixture"
    component={Fixture}
    durationInFrames={30}
    fps={30}
    width={1280}
    height={720}
    defaultProps={{color: '#204060', audio_file: 'fixture.wav', audio_duration_seconds: 1}}
    calculateMetadata={({props}) => ({durationInFrames: Math.ceil(props.audio_duration_seconds * 30)})}
  />
);
