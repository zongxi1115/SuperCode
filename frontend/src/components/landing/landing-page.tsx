import { ArrowUp, ChevronDown, Code2, FileText, Languages, PenLine } from "lucide-react";
import { useState } from "react";
import type { ReactNode } from "react";

const translations = {
  en: {
    login: "Login",
    try: "Try SuperCode",
    product: "Product",
    explore: "Explore here",
    title: "Meet your thinking partner",
    subtitle: "Tackle any big, bold, bewildering challenge with SuperCode.",
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
    title: "遇见你的思考伙伴",
    subtitle: "用 SuperCode 解决任何重大、大胆、令人困惑的挑战。",
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

  const t = translations[lang];

  const toggleLang = () => {
    setLang((prev) => (prev === "en" ? "zh" : "en"));
  };

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
          <h1>{t.title}</h1>
          <p>{t.subtitle}</p>

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
