/// <reference types="vite/client" />

interface Window {
  fabricDesktop?: {
    isDesktop: boolean;
    platform: string;
    saveFile(options: { path?: string; filename: string; bytes: number[]; filters?: Array<{ name: string; extensions: string[] }> }): Promise<string | null>;
    openProject(): Promise<{ path: string; name: string; bytes: number[] } | null>;
  };
}
