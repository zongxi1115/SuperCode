import { ArrowUp, ChevronDown, Code2, FileText, Github, Languages, PenLine } from "lucide-react";
import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "motion/react";
import type { ReactNode } from "react";

const translations = {
  en: {
    login: "Login",
    try: "Try SuperCode",
    product: "Product",
    explore: "Explore here",
    titlePrefix: "Your AI",
    titleSuffix: "companion",
    rotatingWords: ["coding", "thinking", "planning", "debugging", "building", "creating"],
    subtitle: "Write, debug, and ship better code with SuperCode by your side.",
    placeholder: "How can I help you today?",
    ask: "Ask SuperCode",
    write: "Write",
    learn: "Learn",
    code: "Code",
  },
  zh: {
    login: "登录",
    try: "试用 SuperCode",
    product: "产品",
    explore: "探索更多",
    titlePrefix: "你的 AI",
    titleSuffix: "伙伴",
    rotatingWords: ["编程", "思考", "规划", "调试", "构建", "创造"],
    subtitle: "从代码到上线，SuperCode 让开发更轻松。",
    placeholder: "今天我能帮您什么？",
    ask: "询问 SuperCode",
    write: "写作",
    learn: "学习",
    code: "编程",
  },
};

function PromptShortcut({
  icon,
  label,
}: {
  icon: ReactNode;
  label: string;
}) {
  return (
    <button className="landing-shortcut" type="button">
      {icon}
      <span>{label}</span>
    </button>
  );
}

export function LandingPage() {
  const [prompt, setPrompt] = useState("");
  const [lang, setLang] = useState<"en" | "zh">("en");
  const [wordIndex, setWordIndex] = useState(0);

  const t = translations[lang];

  const toggleLang = () => {
    setLang((prev) => (prev === "en" ? "zh" : "en"));
  };

  useEffect(() => {
    const interval = setInterval(() => {
      setWordIndex((prev) => (prev + 1) % t.rotatingWords.length);
    }, 3000);
    return () => clearInterval(interval);
  }, [t.rotatingWords.length]);

  return (
    <main className="landing-stage">
      <iframe
        className="landing-background"
        title="SuperCode recursive logo animation"
        src="/landing-logo-background.html"
        aria-hidden="true"
      />

      <header className="landing-header">
        <a className="landing-brand" href="/landing" aria-label="SuperCode landing">
          <img src="/supercode-logo.svg" alt="" className="landing-brand-mark" />
          <span>SuperCode</span>
        </a>
        <div className="landing-actions">
          <a
            className="landing-github"
            href="https://github.com/zongxi1115/supercode"
            target="_blank"
            rel="noopener noreferrer"
            aria-label="Star on GitHub"
          >
            <Github className="landing-github-icon" aria-hidden="true" />
            <span>GitHub</span>
          </a>
          <button
            className="landing-lang-toggle"
            type="button"
            onClick={toggleLang}
            aria-label="Toggle language"
          >
            <Languages className="landing-lang-icon" aria-hidden="true" />
          </button>
          <a className="landing-sales" href="/app">
            {t.login}
          </a>
          <a className="landing-try" href="/app">
            {t.try}
          </a>
        </div>
      </header>

      <div className="landing-subnav">
        <span>{t.product}</span>
        <button className="landing-explore" type="button">
          <span>{t.explore}</span>
          <ChevronDown className="landing-nav-chevron" aria-hidden="true" />
        </button>
      </div>

      <section className="landing-hero" aria-label="SuperCode introduction">
        <div className="landing-copy">
          <h1 lang={lang}>
            <span>{t.titlePrefix} </span>
            <span className="rotating-word-container">
              <AnimatePresence mode="wait">
                <motion.span
                  key={wordIndex}
                  className="rotating-word"
                  initial={{ y: 20, opacity: 0 }}
                  animate={{ y: 0, opacity: 1 }}
                  exit={{ y: -20, opacity: 0 }}
                  transition={{ duration: 0.4, ease: "easeInOut" }}
                >
                  {t.rotatingWords[wordIndex]}
                </motion.span>
              </AnimatePresence>
            </span>
            <span> {t.titleSuffix}</span>
          </h1>
          <p lang={lang}>{t.subtitle}</p>

          <div className="landing-prompt">
            <label className="sr-only" htmlFor="landing-prompt">
              {t.placeholder}
            </label>
            <input
              id="landing-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value)}
              placeholder={t.placeholder}
              className="landing-prompt-input"
            />
            <button className="landing-ask" type="button">
              <span>{t.ask}</span>
              <ArrowUp className="landing-ask-icon" aria-hidden="true" />
            </button>
          </div>

          <div className="landing-shortcuts" aria-label="Prompt examples">
            <PromptShortcut icon={<PenLine aria-hidden="true" />} label={t.write} />
            <PromptShortcut icon={<FileText aria-hidden="true" />} label={t.learn} />
            <PromptShortcut icon={<Code2 aria-hidden="true" />} label={t.code} />
          </div>
        </div>
      </section>
    </main>
  );
}
