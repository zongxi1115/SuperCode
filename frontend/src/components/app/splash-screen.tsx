import { motion } from 'motion/react';

const floatingParticles = Array.from({ length: 6 }, (_, i) => ({
  id: i,
  x: 15 + (i * 14) % 70,
  delay: i * 0.7,
  duration: 4 + (i % 3),
  size: 2 + (i % 3),
}));

export function SplashScreen({ workspace }: { workspace?: string }) {
  return (
    <motion.div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-hidden"
      initial={{ opacity: 1 }}
      exit={{ opacity: 0, scale: 1.03 }}
      transition={{ duration: 0.7, ease: [0.4, 0, 0.2, 1] }}
    >
      {/* Background gradient matching the app theme */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(ellipse at 50% 30%, rgba(0, 156, 255, 0.2) 0%, transparent 60%), radial-gradient(ellipse at 80% 80%, rgba(0, 91, 170, 0.08) 0%, transparent 50%), linear-gradient(180deg, #00131f 0%, #000b14 50%, #000509 100%)',
        }}
      />

      {/* Animated glows */}
      <motion.div
        className="absolute w-96 h-96 rounded-full"
        style={{
          left: '50%',
          top: '40%',
          transform: 'translate(-50%, -50%)',
          background: 'radial-gradient(circle, rgba(0, 156, 255, 0.12) 0%, transparent 70%)',
          filter: 'blur(80px)',
        }}
        animate={{ scale: [1, 1.3, 1], opacity: [0.3, 0.6, 0.3] }}
        transition={{ duration: 4, repeat: Infinity, ease: 'easeInOut' }}
      />

      <motion.div
        className="absolute w-64 h-64 rounded-full"
        style={{
          left: '25%',
          top: '65%',
          background: 'radial-gradient(circle, rgba(0, 91, 170, 0.1) 0%, transparent 70%)',
          filter: 'blur(60px)',
        }}
        animate={{ scale: [1.1, 0.85, 1.1], opacity: [0.15, 0.4, 0.15] }}
        transition={{ duration: 5, repeat: Infinity, ease: 'easeInOut', delay: 0.8 }}
      />

      <motion.div
        className="absolute w-48 h-48 rounded-full"
        style={{
          right: '20%',
          top: '25%',
          background: 'radial-gradient(circle, rgba(74, 190, 255, 0.08) 0%, transparent 70%)',
          filter: 'blur(50px)',
        }}
        animate={{ scale: [0.9, 1.2, 0.9], opacity: [0.1, 0.35, 0.1] }}
        transition={{ duration: 3.5, repeat: Infinity, ease: 'easeInOut', delay: 1.5 }}
      />

      {/* Floating particles */}
      {floatingParticles.map((p) => (
        <motion.div
          key={p.id}
          className="absolute rounded-full bg-sky-400/30"
          style={{
            left: `${p.x}%`,
            bottom: '-5%',
            width: p.size,
            height: p.size,
          }}
          animate={{ y: [0, -window.innerHeight * 1.2], opacity: [0, 0.6, 0] }}
          transition={{
            duration: p.duration,
            delay: p.delay,
            repeat: Infinity,
            ease: 'easeOut',
          }}
        />
      ))}

      {/* Main content */}
      <div className="relative z-10 flex flex-col items-center gap-7">
        {/* Logo */}
        <motion.div
          className="relative"
          initial={{ scale: 0.3, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 180, damping: 18, delay: 0.1 }}
        >
          {/* Rotating ring */}
          <motion.div
            className="absolute inset-0 rounded-2xl"
            style={{
              margin: '-6px',
              border: '1.5px solid transparent',
              borderTopColor: 'rgba(0, 156, 255, 0.45)',
              borderRightColor: 'rgba(0, 156, 255, 0.12)',
            }}
            animate={{ rotate: 360 }}
            transition={{ duration: 3, repeat: Infinity, ease: 'linear' }}
          />

          {/* Glow behind logo */}
          <motion.div
            className="absolute inset-0 rounded-2xl"
            style={{
              background: 'radial-gradient(circle, rgba(0, 156, 255, 0.35) 0%, transparent 70%)',
              filter: 'blur(24px)',
              margin: '-16px',
            }}
            animate={{ opacity: [0.4, 0.8, 0.4] }}
            transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
          />

          <div
            className="relative w-20 h-20 flex items-center justify-center rounded-2xl"
            style={{
              background: 'linear-gradient(135deg, rgba(0, 156, 255, 0.14), rgba(0, 24, 44, 0.2))',
              border: '1px solid rgba(0, 156, 255, 0.24)',
              boxShadow: '0 0 40px rgba(0, 156, 255, 0.14), inset 0 1px 0 rgba(255,255,255,0.05)',
            }}
          >
            <motion.img
              src="/supercode-logo.svg"
              alt="SuperCode"
              className="h-14 w-14 rounded-xl"
              initial={{ opacity: 0, scale: 0.86 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.45, delay: 0.25, ease: 'easeOut' }}
            />
          </div>
        </motion.div>

        {/* Title and status text */}
        <motion.div
          className="flex flex-col items-center gap-2.5"
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.5, duration: 0.6, ease: [0.25, 0.1, 0.25, 1] }}
        >
          <h1 className="text-2xl font-bold text-white/95 tracking-tight">Super Code</h1>
          <p className="text-sm text-sky-200/55">正在恢复工作区</p>
          {workspace && (
            <motion.p
              className="text-[11px] text-sky-200/35 max-w-[260px] truncate text-center font-mono"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ delay: 0.8 }}
            >
              {workspace}
            </motion.p>
          )}
        </motion.div>

        {/* Shimmer progress bar */}
        <motion.div
          className="relative w-44 h-[2px] rounded-full overflow-hidden"
          style={{ background: 'rgba(0, 156, 255, 0.12)' }}
          initial={{ opacity: 0, scaleX: 0 }}
          animate={{ opacity: 1, scaleX: 1 }}
          transition={{ delay: 0.7, duration: 0.5, ease: [0.25, 0.1, 0.25, 1] }}
        >
          <motion.div
            className="absolute inset-y-0 w-2/5 rounded-full"
            style={{
              background: 'linear-gradient(90deg, transparent, rgba(0, 156, 255, 0.7), rgba(120, 215, 255, 0.9), transparent)',
            }}
            animate={{ x: ['-100%', '350%'] }}
            transition={{ duration: 1.8, repeat: Infinity, ease: [0.4, 0, 0.2, 1], repeatDelay: 0.3 }}
          />
        </motion.div>
      </div>

      {/* Bottom edge glow */}
      <motion.div
        className="absolute bottom-0 left-0 right-0 h-px"
        style={{
          background: 'linear-gradient(90deg, transparent 10%, rgba(0, 156, 255, 0.3) 50%, transparent 90%)',
        }}
        animate={{ opacity: [0.2, 0.6, 0.2] }}
        transition={{ duration: 2.5, repeat: Infinity, ease: 'easeInOut' }}
      />
    </motion.div>
  );
}
