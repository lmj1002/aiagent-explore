-- ============================================================================
-- Issue → PR 自动化流水线 状态追踪数据库 Schema
--
-- 设计原则:
-- 1. 状态转换不可变 — 每条转换都是 INSERT，永不 UPDATE 状态字段
-- 2. 重试链路完整可追溯 — 每次重试独立记录，关联到具体的问题和修复
-- 3. 代码一致性锚点 — 用 git tree-hash 确保安全审查通过的代码 = 最终推送的代码
-- 4. 门禁状态显式化 — 所有人工确认点都有显式状态记录
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1. 流水线运行主表
-- 一次 /auto-fix 调用 = 一条 pipeline_runs 记录
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              TEXT PRIMARY KEY,          -- run_id: UUID v7
    issue_id        INTEGER NOT NULL,          -- GitHub Issue 数据库 ID
    issue_number    INTEGER NOT NULL,          -- GitHub Issue 显示编号 (#1, #2, ...)
    issue_title     TEXT,                      -- Issue 标题快照（启动时记录）
    run_state       TEXT NOT NULL DEFAULT 'INIT',  -- 粗粒度状态: INIT | IN_PROGRESS | AWAITING_GATE | BLOCKED | COMPLETED | FAILED | CANCELLED
    current_phase   TEXT,                      -- 细粒度阶段: phase0_validate | phase1_analyze | phase2_plan | phase3_develop | phase4_security | phase4_fix | phase5_review | phase5_fix | phase6_push | phase7_deliver
    branch_name     TEXT,                      -- 功能分支名
    base_branch     TEXT DEFAULT 'main',       -- 基准分支
    pr_url          TEXT,                      -- 最终 PR 链接
    pr_number       INTEGER,                   -- PR 编号
    security_retry_count  INTEGER DEFAULT 0,   -- Phase 4 已重试次数
    review_retry_count    INTEGER DEFAULT 0,   -- Phase 5 已重试次数
    security_pass_commit  TEXT,                -- Phase 4 通过时的 commit SHA（一致性锚点）
    error_message   TEXT,                      -- 最近的错误信息
    error_phase     TEXT,                      -- 错误发生的阶段
    metadata        TEXT DEFAULT '{}',         -- JSON: 额外上下文 (dry_run, skip_security 等)
    started_at      TEXT,                      -- ISO 8601
    updated_at      TEXT,                      -- ISO 8601
    completed_at    TEXT,                      -- ISO 8601
    CHECK (run_state IN ('INIT', 'IN_PROGRESS', 'AWAITING_GATE', 'BLOCKED', 'COMPLETED', 'FAILED', 'CANCELLED'))
);

-- 索引：按 Issue 编号查找最近的运行
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_issue ON pipeline_runs(issue_number, started_at DESC);

-- ----------------------------------------------------------------------------
-- 2. 状态转换审计日志
-- 每一次状态变更都 INSERT 一条记录，永不修改
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS state_transitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    from_state      TEXT,                      -- 可为 NULL（首次转换）
    to_state        TEXT NOT NULL,
    from_phase      TEXT,                      -- 可为 NULL
    to_phase        TEXT,                      -- 可为 NULL
    triggered_by    TEXT NOT NULL DEFAULT 'orchestrator',  -- orchestrator | human | system
    reason          TEXT,                      -- 转换原因（人类可读）
    context_json    TEXT DEFAULT '{}',         -- JSON: 额外上下文
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_transitions_run ON state_transitions(run_id, created_at);

-- ----------------------------------------------------------------------------
-- 3. 重试尝试记录
-- 每次安全审查/代码审查不通过后的修复+重审 = 一条 retry_attempts 记录
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS retry_attempts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    phase           TEXT NOT NULL,              -- 'security' | 'review'
    attempt_number  INTEGER NOT NULL,           -- 第几次尝试 (1-based)
    max_attempts    INTEGER NOT NULL,           -- 该阶段最大重试次数
    -- 审查发现的问题
    issues_found_json TEXT DEFAULT '[]',        -- JSON: [{id, severity, category, description, file_path, line_range}]
    -- 针对问题的修复
    fixes_applied_json TEXT DEFAULT '[]',       -- JSON: [{issue_id, fix_description, files_changed, commit_sha}]
    -- 修复前/后的代码快照
    code_snapshot_before TEXT,                  -- 修复前 commit SHA
    code_snapshot_after  TEXT,                  -- 修复后 commit SHA
    -- 重审结果
    result          TEXT,                       -- 'pass' | 'fail' | 'partial'
    report_file     TEXT,                      -- 审查报告文件路径
    reviewer_notes  TEXT,                      -- 审查者备注
    started_at      TEXT,                      -- ISO 8601
    completed_at    TEXT,                      -- ISO 8601
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(id),
    UNIQUE(run_id, phase, attempt_number)      -- 同一 phase 的同一 attempt 不重复
);

CREATE INDEX IF NOT EXISTS idx_retries_run ON retry_attempts(run_id, phase, attempt_number);

-- ----------------------------------------------------------------------------
-- 4. 阶段产物注册表
-- 记录每个阶段产出的文件、commit、报告等
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS phase_artifacts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    phase           TEXT NOT NULL,              -- phase0_validate ... phase7_deliver
    artifact_type   TEXT NOT NULL,              -- 'report' | 'commit' | 'branch' | 'pr' | 'label'
    artifact_subtype TEXT,                      -- 'analysis' | 'plan' | 'security_report' | 'review_report' | 'code' | 'delivery_summary'
    file_path       TEXT,                       -- 文件路径（报告类）
    commit_sha      TEXT,                       -- commit SHA（代码类）
    external_url    TEXT,                       -- 外部链接（PR URL 等）
    content_hash    TEXT,                       -- SHA256（用于检测篡改）
    metadata_json   TEXT DEFAULT '{}',          -- JSON: 额外信息
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_artifacts_run ON phase_artifacts(run_id, phase);

-- ----------------------------------------------------------------------------
-- 5. 数据一致性校验记录
-- 用于记录和验证关键不变量的检查结果
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS consistency_checks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    check_point     TEXT NOT NULL,              -- 检查点: 'phase4_to_phase6' | 'phase5_fix_to_security' | 'branch_integrity' | 'pr_issue_link'
    invariant       TEXT NOT NULL,              -- 要检查的不变量描述
    check_result    TEXT NOT NULL,              -- 'pass' | 'fail' | 'skipped'
    detail          TEXT,                      -- 检查详情
    remedial_action TEXT,                      -- 失败后的补救措施
    checked_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_consistency_run ON consistency_checks(run_id, check_point);

-- ----------------------------------------------------------------------------
-- 6. 门禁确认记录
-- 记录所有需要人工确认的门禁点
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gate_confirmations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          TEXT NOT NULL,
    gate_name       TEXT NOT NULL,              -- 'plan_approval' | 'pr_creation' | 'security_override' | 'retry_exhausted'
    confirmed_by    TEXT NOT NULL DEFAULT 'human',  -- 'human' | 'system_auto'
    decision        TEXT NOT NULL,              -- 'approved' | 'rejected' | 'deferred'
    reason          TEXT,                      -- 决策原因
    confirmed_at    TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (run_id) REFERENCES pipeline_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_gates_run ON gate_confirmations(run_id, gate_name);

-- ----------------------------------------------------------------------------
-- 视图：当前活跃的流水线
-- ----------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_active_pipelines AS
SELECT
    pr.id,
    pr.issue_number,
    pr.issue_title,
    pr.run_state,
    pr.current_phase,
    pr.branch_name,
    pr.security_retry_count,
    pr.review_retry_count,
    pr.started_at,
    pr.updated_at,
    (SELECT COUNT(*) FROM retry_attempts ra WHERE ra.run_id = pr.id AND ra.phase = 'security') AS security_attempts,
    (SELECT COUNT(*) FROM retry_attempts ra WHERE ra.run_id = pr.id AND ra.phase = 'review') AS review_attempts
FROM pipeline_runs pr
WHERE pr.run_state IN ('INIT', 'IN_PROGRESS', 'AWAITING_GATE', 'BLOCKED');

-- ----------------------------------------------------------------------------
-- 视图：某次运行的完整时间线
-- ----------------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS v_run_timeline AS
SELECT
    st.run_id,
    st.created_at,
    st.from_state || COALESCE(' (' || st.from_phase || ')', '') AS from_status,
    st.to_state || COALESCE(' (' || st.to_phase || ')', '') AS to_status,
    st.triggered_by,
    st.reason
FROM state_transitions st
ORDER BY st.run_id, st.created_at;
