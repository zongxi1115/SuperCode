import { motion, useAnimate } from 'motion/react';
import { useEffect } from 'react';

export function SplashScreen({ workspace }: { workspace?: string }) {
  const isDark = document.documentElement.classList.contains('dark');

  const bgColor = isDark ? '#0a0a0a' : '#fafafa';
  const textColor = isDark ? '#f8f4ea' : '#1a1a1a';
  const subtextColor = isDark ? '#a9a79f' : '#6b6b6b';
  const workspaceColor = isDark ? '#6e6c65' : '#999999';
  const accentColor = 'oklch(0.617 0.254 267.728)';

  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden"
      style={{ background: bgColor }}
      initial={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.5, ease: [0.4, 0, 0.2, 1] }}
    >
      {/* Subtle background gradient */}
      <div
        className="absolute inset-0"
        style={{
          background: isDark
            ? 'radial-gradient(ellipse at center, rgba(158, 71, 255, 0.06) 0%, transparent 60%)'
            : 'radial-gradient(ellipse at center, rgba(158, 71, 255, 0.04) 0%, transparent 60%)',
        }}
      />

      {/* Main content */}
      <div className="relative z-10 flex flex-col items-center">
        {/* Logo to text animation container */}
        <div className="relative flex items-center justify-center" style={{ height: '140px', width: '400px' }}>
          {/* S Logo - scales and moves to become the S in SuperCode */}
          <motion.div
            className="absolute left-1/2"
            style={{ x: '-50%' }}
            initial={{ opacity: 1, scale: 1.2 }}
            animate={{
              opacity: [1, 1, 1, 0],
              scale: [1.2, 1.2, 0.85, 0.85],
              x: ['-50%', '-50%', '-180px', '-180px']
            }}
            transition={{
              duration: 2.5,
              times: [0, 0.35, 0.6, 1],
              ease: [0.4, 0, 0.2, 1]
            }}
          >
            <img
              src="/supercode-logo.svg"
              alt=""
              style={{
                width: '90px',
                height: '90px',
                filter: isDark
                  ? 'brightness(1.1) drop-shadow(0 0 25px rgba(158, 71, 255, 0.5))'
                  : 'brightness(0.95) drop-shadow(0 0 20px rgba(158, 71, 255, 0.4))'
              }}
            />
          </motion.div>

          {/* SuperCode text - emerges as logo transforms */}
          <motion.div
            className="absolute left-1/2"
            style={{
              x: '-50%',
              display: 'flex',
              alignItems: 'center'
            }}
            initial={{ opacity: 0 }}
            animate={{ opacity: [0, 0, 1] }}
            transition={{
              duration: 2.5,
              times: [0, 0.5, 1],
              ease: [0.4, 0, 0.2, 1]
            }}
          >
            <h1
              style={{
                color: textColor,
                fontFamily: 'Georgia, "Times New Roman", serif',
                fontSize: '56px',
                fontWeight: 700,
                letterSpacing: '-0.02em',
                whiteSpace: 'nowrap',
                display: 'flex'
              }}
            >
              <motion.span
                initial={{ opacity: 0, x: -20 }}
                animate={{ opacity: [0, 0, 1], x: [-20, -20, 0] }}
                transition={{
                  duration: 2.5,
                  times: [0, 0.6, 0.85],
                  ease: [0.4, 0, 0.2, 1]
                }}
              >
                S
              </motion.span>
              <motion.span
                initial={{ opacity: 0, x: -15 }}
                animate={{ opacity: [0, 0, 1], x: [-15, -15, 0] }}
                transition={{
                  duration: 2.5,
                  times: [0, 0.65, 0.9],
                  ease: [0.4, 0, 0.2, 1]
                }}
              >
                uper
              </motion.span>
              <motion.span
                initial={{ opacity: 0, x: -10 }}
                animate={{ opacity: [0, 0, 1], x: [-10, -10, 0] }}
                transition={{
                  duration: 2.5,
                  times: [0, 0.7, 0.95],
                  ease: [0.4, 0, 0.2, 1]
                }}
              >
                Code
              </motion.span>
            </h1>
          </motion.div>
        </div>

        {/* Status text */}
        <motion.div
          className="flex flex-col items-center gap-2 mt-8"
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 2, duration: 0.6 }}
        >
          <p
            style={{
              color: subtextColor,
              fontFamily: '"DM Sans", sans-serif',
              fontSize: '16px',
              fontWeight: 500
            }}
          >
            正在恢复工作区
          </p>
          {workspace && (
            <motion.p
              className="max-w-[320px] truncate text-center"
              style={{
                color: workspaceColor,
                fontFamily: '"DM Sans", sans-serif',
                fontSize: '13px'
              }}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 2.3 }}
            >
              {workspace}
            </motion.p>
          )}
        </motion.div>

        {/* Elegant loading dots */}
        <motion.div
          className="flex items-center gap-1.5 mt-6"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 2.2, duration: 0.5 }}
        >
          {[0, 1, 2].map((i) => (
            <motion.div
              key={i}
              className="rounded-full"
              style={{
                width: '4px',
                height: '4px',
                background: accentColor,
              }}
              animate={{
                opacity: [0.3, 1, 0.3],
                scale: [1, 1.3, 1]
              }}
              transition={{
                duration: 1.5,
                repeat: Infinity,
                delay: 2.2 + i * 0.2,
                ease: 'easeInOut'
              }}
            />
          ))}
        </motion.div>
      </div>
    </motion.div>
  );
}
