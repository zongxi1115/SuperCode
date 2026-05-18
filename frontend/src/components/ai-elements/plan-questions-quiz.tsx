import { useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import { ChevronRight, ChevronLeft, Check, Send } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Textarea } from "@/components/ui/textarea";

export type QuestionType = "single" | "multiple" | "text";

export interface Option {
  id: string;
  label: string;
}

export interface Question {
  id: string;
  type: QuestionType;
  title: string;
  description?: string;
  options?: Option[];
  placeholder?: string;
  required?: boolean;
  includeOtherOption?: boolean;
}

export type QuizSubmission = Record<
  string,
  {
    value: string | string[];
    otherText?: string;
  }
>;

type PlanQuestionsQuizProps = {
  questions: Question[];
  initialAnswers?: QuizSubmission;
  submitted?: boolean;
  onSubmit?: (answers: QuizSubmission) => void | Promise<void>;
  embedded?: boolean;
  title?: string;
  description?: string;
};

const OTHER_OPTION_ID = "__other__";

export function PlanQuestionsQuiz({
  questions,
  initialAnswers,
  submitted = false,
  onSubmit,
  embedded = false,
  title,
  description,
}: PlanQuestionsQuizProps) {
  const [currentIdx, setCurrentIdx] = useState(0);
  const [direction, setDirection] = useState(1);
  const [answers, setAnswers] = useState<Record<string, string | string[]>>(() => {
    const next: Record<string, string | string[]> = {};
    for (const [questionId, answer] of Object.entries(initialAnswers ?? {})) {
      next[questionId] = answer.value;
    }
    return next;
  });
  const [otherTexts, setOtherTexts] = useState<Record<string, string>>(() => {
    const next: Record<string, string> = {};
    for (const [questionId, answer] of Object.entries(initialAnswers ?? {})) {
      next[questionId] = answer.otherText ?? "";
    }
    return next;
  });
  const [isSubmitted, setIsSubmitted] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [validationMessage, setValidationMessage] = useState<string | null>(null);

  const currentQuestion = questions[currentIdx];
  const totalQuestions = questions.length;
  const progress = (currentIdx / totalQuestions) * 100;

  const buildSubmission = (): QuizSubmission => {
    const submission: QuizSubmission = {};
    for (const question of questions) {
      submission[question.id] = {
        value:
          question.type === "multiple"
            ? ((answers[question.id] as string[]) ?? []).filter(
                (item) => item !== OTHER_OPTION_ID,
              )
            : question.type === "single" && answers[question.id] === OTHER_OPTION_ID
              ? ""
              : (answers[question.id] ?? (question.type === "multiple" ? [] : "")),
        otherText: otherTexts[question.id]?.trim() || undefined,
      };
    }
    return submission;
  };

  const validateCurrentQuestion = () => {
    if (!currentQuestion) return true;
    const required = currentQuestion.required ?? true;
    if (!required) {
      setValidationMessage(null);
      return true;
    }

    const answer = answers[currentQuestion.id];
    const otherText = otherTexts[currentQuestion.id]?.trim() ?? "";

    if (currentQuestion.type === "single") {
      if (!answer) {
        setValidationMessage("请选择一个选项后再继续。");
        return false;
      }
      if (answer === OTHER_OPTION_ID && !otherText) {
        setValidationMessage("请补充更多信息后再继续。");
        return false;
      }
    }

    if (currentQuestion.type === "multiple") {
      const selected = (answer as string[] | undefined) ?? [];
      if (selected.length === 0) {
        setValidationMessage("请至少选择一个选项后再继续。");
        return false;
      }
      if (selected.includes(OTHER_OPTION_ID) && !otherText) {
        setValidationMessage("请补充更多信息后再继续。");
        return false;
      }
    }

    if (currentQuestion.type === "text") {
      if (!String(answer ?? "").trim()) {
        setValidationMessage("请补充更多信息后再继续。");
        return false;
      }
    }

    setValidationMessage(null);
    return true;
  };

  const handleNext = () => {
    if (!validateCurrentQuestion()) return;
    if (currentIdx < totalQuestions - 1) {
      setDirection(1);
      setCurrentIdx((prev) => prev + 1);
    }
  };

  const handlePrev = () => {
    if (currentIdx > 0) {
      setDirection(-1);
      setCurrentIdx((prev) => prev - 1);
    }
  };

  const handleSubmit = async () => {
    if (!validateCurrentQuestion()) return;
    setIsSubmitting(true);
    try {
      await onSubmit?.(buildSubmission());
      setIsSubmitted(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAnswerChange = (qId: string, val: string | string[]) => {
    setAnswers((prev) => ({ ...prev, [qId]: val }));
    setValidationMessage(null);
  };

  const handleOtherTextChange = (qId: string, value: string) => {
    setOtherTexts((prev) => ({ ...prev, [qId]: value }));
    setValidationMessage(null);
  };

  const variants = {
    enter: (nextDirection: number) => ({
      x: nextDirection > 0 ? 50 : -50,
      opacity: 0,
      scale: 0.98,
    }),
    center: {
      zIndex: 1,
      x: 0,
      opacity: 1,
      scale: 1,
    },
    exit: (nextDirection: number) => ({
      zIndex: 0,
      x: nextDirection < 0 ? 50 : -50,
      opacity: 0,
      scale: 0.98,
    }),
  };

  const listVariants = {
    hidden: {},
    visible: {
      transition: {
        staggerChildren: 0.1,
      },
    },
  };

  const itemVariants = {
    hidden: { opacity: 0, y: 15 },
    visible: {
      opacity: 1,
      y: 0,
      transition: { type: "spring", stiffness: 400, damping: 30 },
    },
  };

  if (submitted || isSubmitted) {
    return (
      <div className={embedded ? "w-full" : "flex min-h-screen items-center justify-center bg-zinc-50 p-6 dark:bg-zinc-950"}>
        <motion.div
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: "spring", bounce: 0.5 }}
          className={embedded ? "w-full" : undefined}
        >
          <Card className={`w-full ${embedded ? "" : "max-w-md"} border-none shadow-xl`}>
            <CardHeader className="text-center">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ delay: 0.2, type: "spring", bounce: 0.6 }}
                className="mx-auto mb-4 flex h-20 w-20 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/20"
              >
                <Check className="h-10 w-10 text-green-600 dark:text-green-400" />
              </motion.div>
              <CardTitle className="text-2xl font-bold tracking-tight">
                问答完成
              </CardTitle>
              <CardDescription className="text-base text-muted-foreground mt-2">
                感谢你补充这些信息，我会据此继续完善计划。
              </CardDescription>
            </CardHeader>
          </Card>
        </motion.div>
      </div>
    );
  }

  if (!currentQuestion) {
    return null;
  }

  return (
    <div className={embedded ? "w-full" : "flex min-h-screen flex-col items-center justify-center bg-zinc-50 p-6 dark:bg-zinc-950"}>
      <div className={`w-full ${embedded ? "" : "max-w-xl"}`}>
        {(title || description) && (
          <div className="mb-8 space-y-2">
            {title ? (
              <h3 className="text-lg font-semibold tracking-tight">{title}</h3>
            ) : null}
            {description ? (
              <p className="text-sm text-muted-foreground">{description}</p>
            ) : null}
          </div>
        )}
        <div className="mb-8 space-y-2">
          <div className="flex justify-between text-sm font-medium text-muted-foreground">
            <span className="flex items-center gap-1">
              问题
              <span className="relative inline-flex overflow-hidden min-w-[1ch] justify-center">
                <AnimatePresence mode="popLayout" custom={direction} initial={false}>
                  <motion.span
                    key={currentIdx}
                    custom={direction}
                    initial={(nextDirection) => ({
                      y: nextDirection > 0 ? 20 : -20,
                      opacity: 0,
                    })}
                    animate={{ y: 0, opacity: 1 }}
                    exit={(nextDirection) => ({
                      y: nextDirection > 0 ? -20 : 20,
                      opacity: 0,
                    })}
                    transition={{ type: "spring", stiffness: 400, damping: 30 }}
                    className="inline-block"
                  >
                    {currentIdx + 1}
                  </motion.span>
                </AnimatePresence>
              </span>
              / {totalQuestions}
            </span>
            <span className="flex items-center">
              <span className="relative inline-flex overflow-hidden justify-end min-w-[2ch]">
                <AnimatePresence mode="popLayout" custom={direction} initial={false}>
                  <motion.span
                    key={progress}
                    custom={direction}
                    initial={(nextDirection) => ({
                      y: nextDirection > 0 ? 20 : -20,
                      opacity: 0,
                    })}
                    animate={{ y: 0, opacity: 1 }}
                    exit={(nextDirection) => ({
                      y: nextDirection > 0 ? -20 : 20,
                      opacity: 0,
                    })}
                    transition={{ type: "spring", stiffness: 400, damping: 30 }}
                    className="inline-block"
                  >
                    {Math.round(progress)}
                  </motion.span>
                </AnimatePresence>
              </span>
              %
            </span>
          </div>
          <Progress value={progress} className="h-2 w-full rounded-full" />
        </div>

        <div className="relative">
          <AnimatePresence mode="popLayout" initial={false} custom={direction}>
            <motion.div
              key={currentIdx}
              custom={direction}
              variants={variants}
              initial="enter"
              animate="center"
              exit="exit"
              transition={{
                x: { type: "spring", stiffness: 300, damping: 30 },
                opacity: { duration: 0.2 },
              }}
              className={embedded ? "w-full" : "absolute w-full"}
            >
              <Card className="border-none shadow-xl ring-1 ring-zinc-200 dark:ring-zinc-800">
                <CardHeader>
                  <CardTitle className="leading-snug tracking-tight text-xl font-semibold">
                    {currentQuestion.title}
                  </CardTitle>
                  {currentQuestion.description && (
                    <CardDescription className="text-sm">
                      {currentQuestion.description}
                    </CardDescription>
                  )}
                </CardHeader>
                <CardContent className="pt-2 pb-6">
                  {currentQuestion.type === "single" && (
                    <motion.div
                      variants={listVariants}
                      initial="hidden"
                      animate="visible"
                      className="flex flex-col gap-3"
                    >
                      {[...(currentQuestion.options ?? []), ...(currentQuestion.includeOtherOption === false ? [] : [{ id: OTHER_OPTION_ID, label: "其他，请输入" }])].map((opt) => {
                        const isSelected = answers[currentQuestion.id] === opt.id;
                        return (
                          <motion.div
                            variants={itemVariants}
                            key={opt.id}
                            whileHover={{ scale: 1.01 }}
                            whileTap={{ scale: 0.99 }}
                            onClick={() => handleAnswerChange(currentQuestion.id, opt.id)}
                            className={`relative cursor-pointer rounded-xl border p-4 transition-colors ${
                              isSelected
                                ? "border-primary bg-primary/5"
                                : "border-muted-foreground/20 hover:border-primary/50"
                            }`}
                          >
                            <div className="flex items-center gap-4">
                              <div
                                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
                                  isSelected ? "border-primary" : "border-muted-foreground/30"
                                }`}
                              >
                                <AnimatePresence>
                                  {isSelected && (
                                    <motion.div
                                      initial={{ scale: 0 }}
                                      animate={{ scale: 1 }}
                                      exit={{ scale: 0 }}
                                      className="h-2.5 w-2.5 rounded-full bg-primary"
                                    />
                                  )}
                                </AnimatePresence>
                              </div>
                              <span className="text-sm font-medium">{opt.label}</span>
                            </div>
                          </motion.div>
                        );
                      })}
                      {answers[currentQuestion.id] === OTHER_OPTION_ID && (
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                          <Textarea
                            placeholder="请输入更多信息..."
                            className="min-h-[120px] resize-none text-base"
                            value={otherTexts[currentQuestion.id] ?? ""}
                            onChange={(e) =>
                              handleOtherTextChange(currentQuestion.id, e.target.value)
                            }
                          />
                        </motion.div>
                      )}
                    </motion.div>
                  )}

                  {currentQuestion.type === "multiple" && (
                    <motion.div
                      variants={listVariants}
                      initial="hidden"
                      animate="visible"
                      className="flex flex-col gap-3"
                    >
                      {[...(currentQuestion.options ?? []), ...(currentQuestion.includeOtherOption === false ? [] : [{ id: OTHER_OPTION_ID, label: "其他，请输入" }])].map((opt) => {
                        const selectedIds = (answers[currentQuestion.id] as string[]) || [];
                        const isSelected = selectedIds.includes(opt.id);
                        const toggleOption = () => {
                          const newSelected = isSelected
                            ? selectedIds.filter((sid) => sid !== opt.id)
                            : [...selectedIds, opt.id];
                          handleAnswerChange(currentQuestion.id, newSelected);
                        };

                        return (
                          <motion.div
                            variants={itemVariants}
                            key={opt.id}
                            whileHover={{ scale: 1.01 }}
                            whileTap={{ scale: 0.99 }}
                            onClick={toggleOption}
                            className={`relative cursor-pointer rounded-xl border p-4 transition-colors ${
                              isSelected
                                ? "border-primary bg-primary/5"
                                : "border-muted-foreground/20 hover:border-primary/50"
                            }`}
                          >
                            <div className="flex items-center gap-4">
                              <div
                                className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-md border ${
                                  isSelected
                                    ? "border-primary bg-primary text-primary-foreground"
                                    : "border-muted-foreground/30"
                                }`}
                              >
                                <AnimatePresence>
                                  {isSelected && (
                                    <motion.svg
                                      viewBox="0 0 24 24"
                                      fill="none"
                                      stroke="currentColor"
                                      strokeWidth="3"
                                      strokeLinecap="round"
                                      strokeLinejoin="round"
                                      className="h-3 w-3"
                                    >
                                      <motion.polyline
                                        initial={{ pathLength: 0 }}
                                        animate={{ pathLength: 1 }}
                                        exit={{ opacity: 0 }}
                                        transition={{ duration: 0.3, ease: "easeOut" }}
                                        points="20 6 9 17 4 12"
                                      />
                                    </motion.svg>
                                  )}
                                </AnimatePresence>
                              </div>
                              <span className="text-sm font-medium">{opt.label}</span>
                            </div>
                          </motion.div>
                        );
                      })}
                      {((answers[currentQuestion.id] as string[]) || []).includes(OTHER_OPTION_ID) && (
                        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                          <Textarea
                            placeholder="请输入更多信息..."
                            className="min-h-[120px] resize-none text-base"
                            value={otherTexts[currentQuestion.id] ?? ""}
                            onChange={(e) =>
                              handleOtherTextChange(currentQuestion.id, e.target.value)
                            }
                          />
                        </motion.div>
                      )}
                    </motion.div>
                  )}

                  {currentQuestion.type === "text" && (
                    <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                      <Textarea
                        placeholder={currentQuestion.placeholder || "请在这里输入你的回答..."}
                        className="min-h-[150px] resize-none text-base"
                        value={(answers[currentQuestion.id] as string) || ""}
                        onChange={(e) =>
                          handleAnswerChange(currentQuestion.id, e.target.value)
                        }
                      />
                    </motion.div>
                  )}
                  {validationMessage ? (
                    <p className="mt-4 text-sm text-destructive">
                      {validationMessage}
                    </p>
                  ) : null}
                </CardContent>
              </Card>
            </motion.div>
          </AnimatePresence>
        </div>

        <div className="mt-6 flex items-center justify-between">
          <Button
            variant="outline"
            size="lg"
            onClick={handlePrev}
            disabled={currentIdx === 0 || isSubmitting}
            className="w-32 transition-all"
          >
            <ChevronLeft className="mr-2 h-4 w-4" />
            上一步
          </Button>

          {currentIdx === totalQuestions - 1 ? (
            <Button size="lg" onClick={() => void handleSubmit()} className="w-32 bg-primary" disabled={isSubmitting}>
              提交
              <Send className="ml-2 h-4 w-4" />
            </Button>
          ) : (
            <Button size="lg" onClick={handleNext} className="w-32" disabled={isSubmitting}>
              下一步
              <ChevronRight className="ml-2 h-4 w-4" />
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
