<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, session } from '../api'

const isManager = computed(() => session.user?.role === 'MANAGER')
const busy = ref(false)
const error = ref('')
const periods = ref<any[]>([])
const periodId = ref('')
const scope = ref<'PUBLISHED' | 'CANDIDATE'>('PUBLISHED')
const candidates = ref<any[]>([])
const candidateId = ref('')
const question = ref('')
const result = ref<any>(null)
const history = ref<any[]>([])

const managerExamples = [
  '本周排班主要依据哪些规则和统计事实？',
  '当前班表有哪些缺岗，确认进度如何？',
  '哪些员工的计划工时差异较大？'
]
const candidateExamples = [
  '为什么推荐这个调班方案？',
  '这个方案相对当前版本改动了什么？',
  '这个方案是否证明了全局最优？'
]
const employeeExamples = [
  '为什么这周给我安排这些班次？',
  '我的晚班和偏好满足情况如何？',
  '哪里可以查看我本周的岗位安排？'
]

const examples = computed(() => {
  if (!isManager.value) return employeeExamples
  return scope.value === 'CANDIDATE' ? candidateExamples : managerExamples
})
const activePeriod = computed(() => periods.value.find(item => String(item.id) === String(periodId.value)))
const activeCandidate = computed(() => candidates.value.find(item => String(item.id) === String(candidateId.value)))
const currentFacts = computed(() => result.value?.facts || {})
const currentSummary = computed(() => currentFacts.value.summary || {})
const currentOutput = computed(() => result.value?.output || {})
const hasPublishedVersion = computed(() => isManager.value
  ? Boolean(activePeriod.value?.current_version_id)
  : Boolean(periodId.value))
const canGenerate = computed(() => (
  Boolean(periodId.value)
  && question.value.trim().length >= 4
  && (scope.value !== 'CANDIDATE' || Boolean(candidateId.value))
  && !busy.value
))

function formatRate(value: number | null | undefined) {
  return value === null || value === undefined ? '—' : `${value}%`
}

function formatTime(value: string) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Shanghai'
  }).format(new Date(value))
}

function candidateLabel(item: any) {
  const metrics = item.metrics || {}
  return `方案 ${item.sequence} · 改动 ${metrics.changed_count || 0} 人 / ${metrics.changed_shift_count || 0} 班`
}

async function loadPeriods() {
  const data = isManager.value ? await api('/periods') : await api('/period-options')
  periods.value = data.items || []
  const preferred = isManager.value
    ? periods.value.find(item => item.current_version_id) || periods.value[0]
    : periods.value[0]
  if (preferred) periodId.value = String(preferred.id)
}

async function loadCandidates() {
  candidates.value = []
  candidateId.value = ''
  if (!isManager.value || !periodId.value) return
  const events = (await api(`/adjustment-events?status=OPEN&period_id=${periodId.value}`)).items || []
  const groups = await Promise.all(events.map((event: any) =>
    api(`/adjustment-events/${event.id}/candidates?status=PROPOSED`)
      .then(data => (data.items || []).map((candidate: any) => ({
        ...candidate, event_label: `${event.work_date} · ${event.shift_name} · ${event.position_name}`
      })))
  ))
  const seen = new Set<string>()
  candidates.value = groups.flat().filter(candidate => {
    if (seen.has(candidate.id)) return false
    seen.add(candidate.id)
    return true
  })
  if (!candidates.value.length && scope.value === 'CANDIDATE') scope.value = 'PUBLISHED'
}

async function changePeriod() {
  result.value = null
  error.value = ''
  busy.value = true
  try {
    await loadCandidates()
    if (isManager.value && !activePeriod.value?.current_version_id) {
      error.value = '该周期暂时没有可解释的当前发布版本'
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function loadHistory() {
  try {
    history.value = (await api('/ai/schedule-explanations?limit=20')).items || []
  } catch (e) {
    error.value = (e as Error).message
  }
}

async function generateExplanation() {
  const value = question.value.trim()
  if (!value) {
    error.value = '请先填写需要解释的问题'
    return
  }
  error.value = ''
  result.value = null
  busy.value = true
  try {
    const payload: any = { period_id: Number(periodId.value), question: value }
    if (isManager.value && scope.value === 'CANDIDATE') payload.candidate_id = Number(candidateId.value)
    result.value = await api('/ai/schedule-explanations', 'POST', payload)
    if (result.value.status === 'FALLBACK') {
      ElMessage.warning('模型服务暂不可用，已显示固定事实说明')
    } else {
      ElMessage.success('方案解释已生成')
    }
    await loadHistory()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function useExample(value: string) {
  question.value = value
  result.value = null
  error.value = ''
}

async function openHistory(item: any) {
  busy.value = true
  error.value = ''
  try {
    result.value = await api(`/ai/schedule-explanations/${item.id}`)
    periodId.value = String(result.value.period_id)
    if (isManager.value && result.value.scope === 'ADJUSTMENT_CANDIDATE') await loadCandidates()
    scope.value = result.value.scope === 'ADJUSTMENT_CANDIDATE' ? 'CANDIDATE' : 'PUBLISHED'
    candidateId.value = result.value.candidate_id || ''
    question.value = result.value.question
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

function changeScope(value: 'PUBLISHED' | 'CANDIDATE') {
  scope.value = value
  result.value = null
  if (value === 'CANDIDATE' && !candidateId.value && candidates.value.length) {
    candidateId.value = String(candidates.value[0].id)
    question.value = candidateExamples[0]
  }
}

onMounted(async () => {
  busy.value = true
  try {
    await loadPeriods()
    await Promise.all([loadCandidates(), loadHistory()])
    if (isManager.value && !activePeriod.value?.current_version_id) {
      error.value = '请选择已有当前发布版本的排班周'
    }
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
})
</script>

<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">智能助手 · F13</span>
      <h1>方案解释</h1>
      <p class="muted">
        {{ isManager ? '基于当前发布班表或动态调班候选的真实指标解释安排依据与取舍。' : '只解释当前发布版本中与本人相关的班次、工时、岗位和偏好事实。' }}
      </p>
    </div>
    <el-tag :type="isManager ? 'primary' : 'success'" effect="plain">
      {{ isManager ? '管理视图' : '仅本人数据' }}
    </el-tag>
  </div>

  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="explanation-alert"/>

  <section class="panel explain-control">
    <div class="explain-filters">
      <div>
        <span class="field-label">排班周</span>
        <el-select v-model="periodId" class="period-select" placeholder="选择排班周" @change="changePeriod">
          <el-option
            v-for="period in periods"
            :key="period.id"
            :label="`${period.week_start} 周一${isManager && !period.current_version_id ? ' · 未发布' : ''}`"
            :value="String(period.id)"
          />
        </el-select>
      </div>
      <div v-if="isManager">
        <span class="field-label">解释对象</span>
        <el-radio-group :model-value="scope" @change="changeScope">
          <el-radio-button value="PUBLISHED">当前发布班表</el-radio-button>
          <el-radio-button value="CANDIDATE" :disabled="!candidates.length">调班候选方案</el-radio-button>
        </el-radio-group>
      </div>
      <div v-if="isManager && scope === 'CANDIDATE'" class="candidate-select">
        <span class="field-label">候选方案</span>
        <el-select v-model="candidateId" placeholder="选择待解释方案">
          <el-option v-for="item in candidates" :key="item.id" :label="candidateLabel(item)" :value="String(item.id)">
            <div class="candidate-option"><strong>{{ candidateLabel(item) }}</strong><small>{{ item.event_label }}</small></div>
          </el-option>
        </el-select>
      </div>
    </div>
    <div class="question-box">
      <span class="field-label">你的问题</span>
      <el-input
        v-model="question"
        type="textarea"
        :rows="3"
        maxlength="500"
        show-word-limit
        resize="vertical"
        placeholder="例如：为什么这周给我安排这些班次？"
        @keydown.ctrl.enter="generateExplanation"
      />
      <div class="question-actions">
        <div class="example-list">
          <el-button v-for="example in examples" :key="example" link type="primary" @click="useExample(example)">
            {{ example }}
          </el-button>
        </div>
        <el-button type="primary" :loading="busy" :disabled="!canGenerate" @click="generateExplanation">
          生成解释
        </el-button>
      </div>
      <p class="privacy-line">问题与按角色过滤后的事实会保存到解释历史，用于回看本次说明，不保存模型密钥。</p>
    </div>
    <div v-if="!hasPublishedVersion" class="no-version-note">所选周期没有当前发布版本，无法生成班表解释。</div>
  </section>

  <div class="explanation-layout">
    <main class="explanation-main">
      <template v-if="result">
        <section class="panel answer-card">
          <div class="answer-heading">
            <div>
              <span class="eyebrow">
                {{ result.scope === 'ADJUSTMENT_CANDIDATE' ? '调班候选解释' : result.scope === 'PERSONAL_SCHEDULE' ? '本人班表解释' : '当前班表解释' }}
              </span>
              <h2>{{ currentOutput.title }}</h2>
            </div>
            <el-tag :type="result.status === 'COMPLETED' ? 'success' : 'warning'" effect="light">
              {{ result.status === 'COMPLETED' ? '模型解释' : '固定事实模板' }}
            </el-tag>
          </div>

          <div class="answer-question">“{{ result.question }}”</div>
          <p class="conclusion">{{ currentOutput.conclusion }}</p>

          <div class="reason-section">
            <h3>解释依据</h3>
            <ol class="reason-list">
              <li v-for="(reason, index) in currentOutput.reasons || []" :key="index">{{ reason }}</li>
            </ol>
          </div>
          <div class="evidence-section">
            <h3>可核验事实</h3>
            <div class="evidence-grid">
              <span v-for="(item, index) in currentOutput.evidence || []" :key="index">{{ item }}</span>
            </div>
          </div>
          <div v-if="(currentOutput.limitations || []).length" class="limitations">
            <h3>边界与限制</h3>
            <p v-for="(item, index) in currentOutput.limitations || []" :key="index">{{ item }}</p>
          </div>
          <div class="answer-meta">
            <span>模型 {{ result.model }}</span>
            <span v-if="result.usage?.total_tokens">本次约 {{ result.usage.total_tokens }} tokens</span>
            <span>{{ formatTime(result.created_at) }}</span>
          </div>
        </section>

        <section class="metric-grid explanation-metrics">
          <template v-if="result.scope === 'ADJUSTMENT_CANDIDATE'">
            <div class="metric-card accent"><span>变更人数</span><strong>{{ currentFacts.candidate?.metrics?.changed_count || 0 }}</strong><small>相对基准版本</small></div>
            <div class="metric-card"><span>变更班次</span><strong>{{ currentFacts.candidate?.metrics?.changed_shift_count || 0 }}</strong><small>个班次</small></div>
            <div class="metric-card"><span>偏好满足</span><strong>{{ currentFacts.candidate?.metrics?.preference_satisfied || 0 }}/{{ currentFacts.candidate?.metrics?.preference_total || 0 }}</strong><small>候选方案指标</small></div>
          </template>
          <template v-else>
            <div class="metric-card"><span>计划班次</span><strong>{{ currentSummary.shift_count || 0 }}</strong><small>人次班次</small></div>
            <div class="metric-card accent"><span>计划工时</span><strong>{{ currentSummary.planned_hours || 0 }}</strong><small>小时</small></div>
            <div class="metric-card"><span>晚班次数</span><strong>{{ currentSummary.evening_count || 0 }}</strong><small>结束不早于22:00</small></div>
            <div class="metric-card"><span>偏好满足率</span><strong>{{ formatRate(currentSummary.preference_rate) }}</strong><small>{{ currentSummary.preference_satisfied || 0 }}/{{ currentSummary.preference_total || 0 }}</small></div>
            <div v-if="isManager" class="metric-card"><span>当前缺岗</span><strong>{{ currentSummary.open_gap_count || 0 }}</strong><small>待处理缺口</small></div>
            <div v-if="isManager" class="metric-card"><span>确认进度</span><strong>{{ formatRate(currentSummary.confirmation_rate) }}</strong><small>{{ currentSummary.confirmation_confirmed || 0 }}/{{ currentSummary.confirmation_total || 0 }}</small></div>
          </template>
        </section>
      </template>

      <section v-else class="panel explanation-empty">
        <div class="empty-mark">?</div>
        <h2>选择一个范围并提出问题</h2>
        <p class="muted">
          {{ isManager ? '解释会引用当前发布版本或候选方案的指标，不会直接修改或发布班表。' : '解释只读取与本人相关的已发布安排，不会展示其他员工数据。' }}
        </p>
        <div class="capability-strip">
          <span>真实版本与指标</span>
          <span>按角色过滤数据</span>
          <span>不证明全局最优</span>
          <span>失败使用固定模板</span>
        </div>
      </section>
    </main>

    <aside class="panel history-panel">
      <div class="section-heading">
        <h2>最近解释</h2>
        <el-button link type="primary" @click="loadHistory">刷新</el-button>
      </div>
      <button v-for="item in history" :key="item.id" class="history-item" @click="openHistory(item)">
        <div>
          <strong>{{ item.output?.title || item.question }}</strong>
          <span>{{ item.question }}</span>
        </div>
        <el-tag size="small" :type="item.status === 'COMPLETED' ? 'success' : 'warning'" effect="plain">
          {{ item.status === 'COMPLETED' ? '模型' : '模板' }}
        </el-tag>
      </button>
      <p v-if="!history.length" class="muted history-empty">还没有解释记录。</p>
      <div class="history-safety">
        <strong>安全边界</strong>
        <p>解释是辅助说明，不是审批结论，不能应用候选方案、发布班表或替代统一校验。</p>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.explanation-alert{margin-bottom:18px}.explain-control{margin-bottom:22px}.explain-filters{display:flex;align-items:flex-end;gap:18px;flex-wrap:wrap;margin-bottom:20px}.field-label{display:block;font-size:12px;color:#64748b;font-weight:600;margin-bottom:8px}.period-select{width:220px}.candidate-select{min-width:300px;flex:1}.candidate-select .el-select{width:100%}.candidate-option strong{display:block;font-size:13px}.candidate-option small{display:block;color:#94a3b8;font-size:11px;margin-top:3px}.question-box{border-top:1px solid #edf1f6;padding-top:18px}.question-actions{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;margin-top:12px}.example-list{display:flex;align-items:center;gap:4px;flex-wrap:wrap}.example-list .el-button{margin-left:0}.privacy-line{margin:9px 0 0;color:#94a3b8;font-size:10px;line-height:1.6}.no-version-note{margin-top:12px;padding:10px 12px;border-radius:8px;background:#fff7ed;color:#9a6a32;font-size:12px}.explanation-layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:22px;align-items:start}.explanation-main{min-width:0}.answer-card{margin-bottom:20px}.answer-heading{display:flex;align-items:flex-start;justify-content:space-between;gap:16px}.answer-heading h2{font-size:22px;margin:0}.answer-question{margin:18px 0 12px;padding:12px 14px;border-left:3px solid #2563eb;background:#f8fbff;color:#475569;font-size:13px;line-height:1.7}.conclusion{font-size:16px;line-height:1.85;color:#1e293b;margin:0 0 22px}.reason-section h3,.evidence-section h3,.limitations h3{font-size:13px;color:#64748b;margin:0 0 11px}.reason-list{margin:0;padding-left:22px;line-height:1.9;color:#334155}.reason-list li{padding-left:4px;margin-bottom:5px}.reason-list li::marker{color:#2563eb;font-weight:700}.evidence-section{margin-top:22px}.evidence-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}.evidence-grid span{background:#f8fafc;border:1px solid #e8eef6;border-radius:8px;padding:10px 12px;color:#475569;font-size:12px;line-height:1.6}.limitations{margin-top:20px;border:1px solid #fde68a;background:#fffbeb;border-radius:9px;padding:14px}.limitations h3{color:#92400e}.limitations p{margin:5px 0 0;color:#92400e;font-size:12px;line-height:1.7}.answer-meta{display:flex;gap:16px;flex-wrap:wrap;margin-top:18px;padding-top:14px;border-top:1px solid #edf1f6;color:#94a3b8;font-size:10px}.explanation-metrics{grid-template-columns:repeat(3,1fr)}.explanation-empty{min-height:380px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:48px}.empty-mark{width:56px;height:56px;border-radius:18px;background:#eff6ff;color:#2563eb;display:grid;place-items:center;font-size:28px;font-weight:700;margin-bottom:18px}.explanation-empty h2{font-size:20px}.explanation-empty p{max-width:620px}.capability-strip{display:flex;gap:8px;flex-wrap:wrap;justify-content:center;margin-top:12px}.capability-strip span{background:#f8fafc;border:1px solid #e8eef6;border-radius:999px;padding:7px 11px;color:#64748b;font-size:11px}.history-panel{position:sticky;top:20px}.history-panel .section-heading{margin-bottom:10px}.history-item{width:100%;display:flex;align-items:flex-start;justify-content:space-between;gap:8px;border:0;border-top:1px solid #edf1f6;background:transparent;padding:13px 2px;text-align:left;color:inherit;cursor:pointer}.history-item:hover{background:#f8fbff}.history-item strong{display:block;font-size:12px;line-height:1.5}.history-item span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;color:#94a3b8;font-size:10px;line-height:1.6;margin-top:4px}.history-empty{padding:20px 0;text-align:center}.history-safety{border-top:1px solid #edf1f6;margin-top:14px;padding-top:14px}.history-safety strong{font-size:11px;color:#64748b}.history-safety p{margin:6px 0 0;color:#94a3b8;font-size:10px;line-height:1.7}
@media(max-width:1100px){.explanation-layout{grid-template-columns:1fr}.history-panel{position:static}.explanation-metrics{grid-template-columns:1fr 1fr}}
@media(max-width:700px){.explain-filters,.question-actions{align-items:stretch;flex-direction:column}.period-select,.candidate-select{width:100%;min-width:0}.evidence-grid,.explanation-metrics{grid-template-columns:1fr}.answer-heading{flex-direction:column}.example-list{flex-direction:column;align-items:flex-start}.question-actions>.el-button{width:100%}}
</style>
