import {
  SiReact,
  SiTypescript,
  SiJavascript,
  SiPython,
  SiJson,
  SiYaml,
  SiRust,
  SiGo,
  SiDocker,
  SiMarkdown,
  SiVite,
  SiTailwindcss,
  SiPostgresql,
  SiPrisma,
  SiVercel,
  SiGit,
  SiLinux,
  SiNodedotjs,
  SiCss,
  SiHtml5,
  SiSvelte,
  SiVuedotjs,
  SiNextdotjs,
  SiPnpm,
  SiNpm,
  SiYarn,
  SiWebpack,
  SiBabel,
  SiEslint,
  SiPrettier,
  SiNginx,
} from "@icons-pack/react-simple-icons";
import type { ReactNode } from "react";

type FileIconEntry = { icon: ReactNode; color: string };

const extIconMap: Record<string, FileIconEntry> = {
  ".tsx": { icon: <SiReact size={14} />, color: "#61DAFB" },
  ".jsx": { icon: <SiReact size={14} />, color: "#61DAFB" },
  ".ts": { icon: <SiTypescript size={14} />, color: "#3178C6" },
  ".js": { icon: <SiJavascript size={14} />, color: "#F7DF1E" },
  ".mjs": { icon: <SiJavascript size={14} />, color: "#F7DF1E" },
  ".cjs": { icon: <SiJavascript size={14} />, color: "#F7DF1E" },
  ".py": { icon: <SiPython size={14} />, color: "#3776AB" },
  ".json": { icon: <SiJson size={14} />, color: "#000000" },
  ".yaml": { icon: <SiYaml size={14} />, color: "#CB171E" },
  ".yml": { icon: <SiYaml size={14} />, color: "#CB171E" },
  ".toml": { icon: <SiYaml size={14} />, color: "#9C4221" },
  ".rs": { icon: <SiRust size={14} />, color: "#000000" },
  ".go": { icon: <SiGo size={14} />, color: "#00ADD8" },
  ".css": { icon: <SiCss size={14} />, color: "#1572B6" },
  ".scss": { icon: <SiCss size={14} />, color: "#CC6699" },
  ".less": { icon: <SiCss size={14} />, color: "#1D365D" },
  ".html": { icon: <SiHtml5 size={14} />, color: "#E34F26" },
  ".md": { icon: <SiMarkdown size={14} />, color: "#083FA1" },
  ".mdx": { icon: <SiMarkdown size={14} />, color: "#083FA1" },
  ".sql": { icon: <SiPostgresql size={14} />, color: "#4169E1" },
  ".prisma": { icon: <SiPrisma size={14} />, color: "#2D3748" },
  ".svelte": { icon: <SiSvelte size={14} />, color: "#FF3E00" },
  ".vue": { icon: <SiVuedotjs size={14} />, color: "#4FC08D" },
};

const nameIconMap: Record<string, FileIconEntry> = {
  "Dockerfile": { icon: <SiDocker size={14} />, color: "#2496ED" },
  "docker-compose.yml": { icon: <SiDocker size={14} />, color: "#2496ED" },
  "docker-compose.yaml": { icon: <SiDocker size={14} />, color: "#2496ED" },
  "vite.config.ts": { icon: <SiVite size={14} />, color: "#646CFF" },
  "vite.config.js": { icon: <SiVite size={14} />, color: "#646CFF" },
  "vite.config.mts": { icon: <SiVite size={14} />, color: "#646CFF" },
  "tailwind.config.ts": { icon: <SiTailwindcss size={14} />, color: "#06B6D4" },
  "tailwind.config.js": { icon: <SiTailwindcss size={14} />, color: "#06B6D4" },
  "next.config.ts": { icon: <SiNextdotjs size={14} />, color: "#000000" },
  "next.config.js": { icon: <SiNextdotjs size={14} />, color: "#000000" },
  "next.config.mjs": { icon: <SiNextdotjs size={14} />, color: "#000000" },
  "package.json": { icon: <SiNodedotjs size={14} />, color: "#339933" },
  "pnpm-lock.yaml": { icon: <SiPnpm size={14} />, color: "#F69220" },
  "package-lock.json": { icon: <SiNpm size={14} />, color: "#CB3837" },
  "yarn.lock": { icon: <SiYarn size={14} />, color: "#2C8EBB" },
  ".gitignore": { icon: <SiGit size={14} />, color: "#F05032" },
  ".gitattributes": { icon: <SiGit size={14} />, color: "#F05032" },
  ".env": { icon: <SiVercel size={14} />, color: "#000000" },
  ".env.example": { icon: <SiVercel size={14} />, color: "#000000" },
  ".env.local": { icon: <SiVercel size={14} />, color: "#000000" },
  "README.md": { icon: <SiMarkdown size={14} />, color: "#083FA1" },
  "requirements.txt": { icon: <SiPython size={14} />, color: "#3776AB" },
  "Makefile": { icon: <SiLinux size={14} />, color: "#FCC624" },
  "webpack.config.js": { icon: <SiWebpack size={14} />, color: "#8DD6F9" },
  "webpack.config.ts": { icon: <SiWebpack size={14} />, color: "#8DD6F9" },
  ".babelrc": { icon: <SiBabel size={14} />, color: "#F9DC3E" },
  "babel.config.js": { icon: <SiBabel size={14} />, color: "#F9DC3E" },
  ".eslintrc": { icon: <SiEslint size={14} />, color: "#4B32C3" },
  ".eslintrc.js": { icon: <SiEslint size={14} />, color: "#4B32C3" },
  ".eslintrc.json": { icon: <SiEslint size={14} />, color: "#4B32C3" },
  "eslint.config.js": { icon: <SiEslint size={14} />, color: "#4B32C3" },
  "eslint.config.mjs": { icon: <SiEslint size={14} />, color: "#4B32C3" },
  ".prettierrc": { icon: <SiPrettier size={14} />, color: "#F7B93E" },
  "prettier.config.js": { icon: <SiPrettier size={14} />, color: "#F7B93E" },
  "nginx.conf": { icon: <SiNginx size={14} />, color: "#009639" },
};

export function getFileIcon(filename: string): FileIconEntry | null {
  const nameMatch = nameIconMap[filename];
  if (nameMatch) return nameMatch;

  const dotIndex = filename.lastIndexOf(".");
  if (dotIndex >= 0) {
    const ext = filename.slice(dotIndex).toLowerCase();
    const extMatch = extIconMap[ext];
    if (extMatch) return extMatch;
  }

  return null;
}
