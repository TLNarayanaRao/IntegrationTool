/// <reference types="vite/client" />

interface Window {
  fabricDesktop?: {
    isDesktop: boolean;
    platform: string;
    saveFile(options: { path?: string; filename: string; bytes: number[]; filters?: Array<{ name: string; extensions: string[] }> }): Promise<string | null>;
    saveProjectFolder(options: { path?: string; folderName: string; project: unknown }): Promise<string | null>;
    openProject(fileType?: "ifproject" | "ifpkg" | "zip" | "json"): Promise<{ path: string; name: string; bytes?: number[]; project?: unknown; kind?: "file" | "folder" } | null>;
    openProjectFolder(): Promise<{ path: string; name: string; project?: unknown; kind?: "folder" } | null>;
    openProjectSource(): Promise<{ path: string; name: string; bytes?: number[]; project?: unknown; kind?: "file" | "folder" } | null>;
    selectCodeArtifact(kind: "java" | "python"): Promise<{ path: string; name: string; kind: string } | null>;
    openUtilityFile(options?: { title?: string; filterName?: string; extensions?: string[] }): Promise<{ id: string; name: string; size: number; modified: number } | null>;
    readUtilityFileChunk(options: { id: string; offset: number; length: number }): Promise<{ offset: number; length: number; size: number; base64: string; eof: boolean }>;
    saveUtilityFileWindow(options: { id: string; offset: number; originalLength: number; base64: string; expectedModified?: number }): Promise<{ name: string; size: number; modified: number }>;
    closeUtilityFile(id: string): Promise<boolean>;
  };
}
