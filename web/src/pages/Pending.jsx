import { motion } from "framer-motion";
import { Clock, LogOut } from "lucide-react";

export default function Pending({ user, onLogout }) {
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <motion.div
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5 }}
        className="w-full max-w-md text-center"
      >
        <div className="card p-8">
          <div className="mx-auto mb-5 grid h-14 w-14 place-items-center rounded-2xl bg-amber/15 text-amber">
            <Clock size={26} />
          </div>
          <h1 className="font-display text-3xl tracking-tight">
            {user.status === "rejected" ? "Access declined" : "Almost there"}
          </h1>
          <p className="mt-3 text-sm text-muted">
            {user.status === "rejected" ? (
              <>Your request wasn’t approved. Contact the admin if this is a mistake.</>
            ) : (
              <>
                Thanks, <span className="text-ink">{user.name || user.email}</span>. Your account is
                waiting for the admin to approve it. You’ll have access as soon as they do.
              </>
            )}
          </p>
          <button onClick={onLogout} className="btn-ghost mx-auto mt-6">
            <LogOut size={15} /> Sign out
          </button>
        </div>
      </motion.div>
    </div>
  );
}
