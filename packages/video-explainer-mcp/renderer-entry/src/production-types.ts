declare module '@project-scenes' {
  export type ProductionScene = {
    id: string;
    type: string;
    title: string;
    from: number;
    durationInFrames: number;
    audio_src: string;
    audioDurationInFrames: number;
    visualPaddingInFrames: number;
    props?: Record<string, unknown>;
  };

  export type ProductionProps = {
    width: number;
    height: number;
    fps: 30;
    durationInFrames: number;
    scenes: ProductionScene[];
  };

  export const sceneRegistry: Record<string, import('react').ComponentType<{scene: ProductionScene}>>;
}
