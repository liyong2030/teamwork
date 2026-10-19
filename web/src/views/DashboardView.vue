<template>
  <div class="page-container">
    <!-- 本周周报状态卡 -->
    <el-card shadow="never" class="week-card" v-loading="loadingWeek">
      <template #header>
        <div class="flex-between">
          <span class="page-title" style="margin: 0">
            {{ week.week_label || '本周周报' }}
          </span>
          <div>
            <el-button type="primary" :disabled="!week.can_generate" @click="onGenerate">
              <el-icon><MagicStick /></el-icon>
              生成周报草稿
            </el-button>
            <el-button :disabled="!week.can_edit" @click="goWrite">
              <el-icon><EditPen /></el-icon>
              {{ week.has_report ? '继续编辑' : '开始填写' }}
            </el-button>
          </div>
        </div>
      </template>

      <el-descriptions :column="4" border size="small">
        <el-descriptions-item label="周报状态">
          <el-tag :type="statusMeta.type" effect="dark">{{ week.status_label }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="提交时间">
          {{ week.submitted_at ? formatDateTime(week.submitted_at) : '尚未提交' }}
        </el-descriptions-item>
        <el-descriptions-item label="截止时间">
          {{ formatDateTime(week.deadline_at) }}
          <el-tag v-if="week.deadline_passed" type="warning" size="small" style="margin-left: 6px">
            已逾期
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="定版时间">
          {{ formatDateTime(week.finalize_at) }}
        </el-descriptions-item>
      </el-descriptions>

      <el-alert
        v-if="week.status === 'missing'"
        type="error"
        :closable="false"
        show-icon
        style="margin-top: 14px"
        title="本周周报尚未提交，定版后将计入未提交统计，请尽快补交。"
      />
      <el-alert
        v-else-if="week.status === 'draft' && !week.deadline_passed"
        type="info"
        :closable="false"
        show-icon
        style="margin-top: 14px"
        title="提示：点击「生成周报草稿」可由本周任务流水自动汇总内容，再人工补充总结与风险。"
      />
    </el-card>

    <el-row :gutter="16">
      <el-col :xs="24" :md="14">
        <el-card shadow="never">
          <template #header>
            <div class="flex-between">
              <span class="page-title" style="margin: 0">我的本周任务</span>
              <el-button text @click="router.push({ name: 'task-list' })">
                查看全部
                <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>
          <el-empty v-if="!myTasks.length" description="本周没有分配给你的任务" :image-size="80" />
          <div v-else class="task-list">
            <div v-for="task in myTasks" :key="task.id" class="task-row" @click="openTask(task)">
              <div class="task-main">
                <el-tag size="small" :type="TASK_STATUS_MAP[task.status]?.type">
                  {{ TASK_STATUS_MAP[task.status]?.label }}
                </el-tag>
                <span class="task-title">{{ task.title }}</span>
              </div>
              <div class="task-meta">
                <span>{{ task.project_name }}</span>
                <span v-if="task.due_date" :class="{ 'text-danger': task.is_overdue }">
                  截止 {{ task.due_date }}
                </span>
                <el-progress
                  :percentage="task.progress"
                  :stroke-width="6"
                  style="width: 90px"
                  :status="task.progress === 100 ? 'success' : undefined"
                />
              </div>
            </div>
          </div>
        </el-card>
      </el-col>

      <el-col :xs="24" :md="10">
        <el-card shadow="never">
          <template #header>
            <span class="page-title" style="margin: 0">我的提交记录（近 12 周）</span>
          </template>
          <el-timeline v-if="history.length">
            <el-timeline-item
              v-for="row in history"
              :key="row.week_start"
              :type="timelineType(row.status)"
              :timestamp="row.week_label"
              size="normal"
            >
              <div class="history-row">
                <el-tag size="small" :type="REPORT_STATUS_MAP[row.status]?.type">
                  {{ row.status_label }}
                </el-tag>
                <span v-if="row.submitted_at" class="muted">
                  {{ formatDateTime(row.submitted_at) }}
                </span>
              </div>
            </el-timeline-item>
          </el-timeline>
          <el-empty v-else description="暂无历史记录" :image-size="80" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never" v-if="store.isLeader" style="margin-top: 16px">
      <template #header>
        <div class="flex-between">
          <span class="page-title" style="margin: 0">管辖范围提交概览</span>
          <el-button text @click="router.push({ name: 'stats' })">
            进入统计看板
            <el-icon><ArrowRight /></el-icon>
          </el-button>
        </div>
      </template>
      <div class="stat-grid" v-if="overview">
        <div class="mini-stat">
          <div class="mini-value">{{ overview.required }}</div>
          <div class="mini-label">应提交</div>
        </div>
        <div class="mini-stat">
          <div class="mini-value text-success">{{ overview.ontime }}</div>
          <div class="mini-label">准时</div>
        </div>
        <div class="mini-stat">
          <div class="mini-value text-warning">{{ overview.late }}</div>
          <div class="mini-label">迟到</div>
        </div>
        <div class="mini-stat">
          <div class="mini-value text-danger">{{ overview.missing }}</div>
          <div class="mini-label">未提交</div>
        </div>
        <div class="mini-stat">
          <div class="mini-value">{{ overview.ontime_rate }}%</div>
          <div class="mini-label">准时率</div>
        </div>
        <div class="mini-stat">
          <div class="mini-value">{{ overview.submit_rate }}%</div>
          <div class="mini-label">提交率</div>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { reportApi } from '@/api/reports'
import { statsApi } from '@/api/stats'
import { taskApi } from '@/api/tasks'
import { useUserStore } from '@/stores/user'
import {
  REPORT_STATUS_MAP,
  TASK_STATUS_MAP,
  formatDateTime,
} from '@/utils/dict'
import type { MyHistoryRow, MyWeekStatus, OverviewData, TaskItem } from '@/types'

const router = useRouter()
const store = useUserStore()

const loadingWeek = ref(false)
const week = ref<MyWeekStatus>({
  week_start: '',
  week_label: '',
  deadline_at: '-',
  finalize_at: '-',
  deadline_passed: false,
  has_report: false,
  report_id: null,
  status: 'draft',
  status_label: '未填写',
  submitted_at: null,
  can_edit: true,
  can_generate: true,
})
const myTasks = ref<TaskItem[]>([])
const history = ref<MyHistoryRow[]>([])
const overview = ref<OverviewData | null>(null)

const statusMeta = computed(() => REPORT_STATUS_MAP[week.value.status] ?? { label: '-', type: 'info' })

function timelineType(status: string) {
  if (status === 'ontime') return 'success'
  if (status === 'missing') return 'danger'
  if (status === 'late' || status === 'makeup' || status === 'by_proxy') return 'warning'
  return 'primary'
}

async function loadAll() {
  loadingWeek.value = true
  try {
    const [w, tasks, hist] = await Promise.all([
      reportApi.myWeekStatus(),
      taskApi.mine(true),
      statsApi.myHistory(12),
    ])
    week.value = w
    myTasks.value = tasks.slice(0, 8)
    history.value = hist
    if (store.isLeader) {
      overview.value = await statsApi.overview().catch(() => null)
    }
  } finally {
    loadingWeek.value = false
  }
}

async function onGenerate() {
  await ElMessageBox.confirm(
    '将按「本周完成任务 / 进行中任务 / 阻塞任务 / 下周到期的任务」自动汇总生成草稿，已有的人工填写内容会保留。是否继续？',
    '生成周报草稿',
    { type: 'info' },
  )
  await reportApi.generate(true)
  ElMessage.success('草稿已生成')
  router.push({ name: 'report-write' })
}

function goWrite() {
  router.push({ name: 'report-write' })
}

function openTask(task: TaskItem) {
  router.push({ name: 'project-detail', params: { id: task.project_id }, query: { task: task.id } })
}

onMounted(loadAll)
</script>

<style scoped>
.week-card {
  margin-bottom: 16px;
}

.task-list {
  display: flex;
  flex-direction: column;
}

.task-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 4px;
  border-bottom: 1px dashed #eef2f7;
  cursor: pointer;
}

.task-row:last-child {
  border-bottom: none;
}

.task-row:hover {
  background: #f8fafc;
}

.task-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.task-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: #6b7280;
  white-space: nowrap;
}

.history-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.mini-stat {
  background: #f8fafc;
  border-radius: 8px;
  padding: 14px 10px;
  text-align: center;
}

.mini-value {
  font-size: 22px;
  font-weight: 600;
  color: #16222f;
}

.mini-label {
  margin-top: 4px;
  font-size: 12px;
  color: #6b7280;
}
</style>
