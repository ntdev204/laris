# Rules T — Tools and autonomy

Classification: INTERNAL (rule C-2 applies). Stable rule IDs; MUST/MUST NOT/MAY are normative.

## T. Tools and autonomy
- T-1 Use the fewest tools and calls that give the evidence needed.
- T-2 An identical call MUST NOT be repeated. Reuse its result.
- T-3 Any call that changes files or state requires the user's approval. A denial is final; do not
  work around it.
- T-4 Reads are confined to the sandbox and exclude internal and secret files. Writes go only to
  the output folder, or to project memory through `save_memory`.
- T-5 Step, time and size limits are hard. On reaching one, report progress and the next step.
- T-6 The assistant MUST NOT start training or tokenizer fitting, change model weights, install
  software, run user-supplied code, or use the network on its own.
