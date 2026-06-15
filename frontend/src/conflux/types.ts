export interface ConfluxOrchestratorConfig {
  model_ref: string;
  token_budget: number;
}

export interface ConfluxSpecialistConfig {
  id: string;
  name: string;
  model_ref: string;
  specialty: string;
  token_budget: number;
}

export interface ConfluxConfig {
  orchestrator: ConfluxOrchestratorConfig;
  specialists: ConfluxSpecialistConfig[];
  require_user_review_per_step: boolean;
  require_orchestrator_diff_review: boolean;
  max_dispatch_depth: number;
}

export interface SpecialistTemplate {
  label: string;
  template: string;
}
