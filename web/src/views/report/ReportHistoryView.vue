<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">我的周报</span>
        <div>
          <el-select v-model="selectedWeek" placeholder="选择周" style="width: 180px" @change="loadDetail">
            <el-option
              v-for="row in history"
              :key="row.week_start"
              :label="row.week_label"
              :value="row.week_start"
            />
          </el-select>
          <el-button style="margin-left: 8px" @click="loadHistory">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </div>

      <el-table :data="history" border stripe style="margin-top: 14px" size="small">
        <el-table-column prop="week_label" label="周次" width="140" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="REPORT_STATUS_MAP[row.status]?.type">
              {{ row.status_label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.submitted_at) }}</template>
        </el-table-column>
        <el-table-column label="有效性" width="100">
          <template #default="{ row }">
            <el-tag :type="row.is_valid ? 'success' : 'info'" size="small">
              {{ row.is_valid ? '有效' : '待定' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作">
          <template #default="{ row }">
            <el-button text type="primary" :disabled="!row.report_id" @click="viewDetail(row)">
              查看
            </el-button>
            <el-button text @click="onExport(row.week_start)">导出</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div class="page-card" v-if="detail">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">
          {{ detail.week_label }} 周报内容
          <span class="muted">（第 {{ detail.version }} 版，共 {{ detail.char_count }} 字）</span>
        </span>
        <el-button text @click="loadRevisions">
          <el-icon><Clock /></el-icon>
          修订历史
        </el-button>
      </div>

      <el-alert
        v-if="detail.review_comment"
        type="success"
        :closable="false"
        show-icon
        style="margin: 12px 0"
        :title="`组长批注：${detail.review_comment}`"
      />

      <el-card
        v-for="section in REPORT_SECTIONS"
        :key="section.key"
        shadow="never"
        style="margin-bottom: 12px"
      >
        <template #header>
          <span class="section-title">
            <el-icon :color="section.color"><component :is="section.icon" /></el-icon>
            {{ section.label }}
          </span>
        </template>
        <ol v-if="grouped[section.key]?.length" class="content-list">
          <li v-for="item in grouped[section.key]" :key="item.id">
            <span>{{ item.content }}</span>
            <el-tag v-if="item.task_id" size="small" effect="plain" style="margin-left: 8px">
              {{ item.task_title }}
            </el-tag>
          </li>
        </ol>
        <span v-else class="muted">未填写</span>
      </el-card>
    </div>

    <el-drawer v-model="revisionVisible" title="修订历史" size="520px">
      <el-timeline>
        <el-timeline-item
          v-for="rev in revisions"
          :key="rev.id"
          :timestamp="formatDateTime(rev.created_at)"
        >
          第 {{ rev.version }} 版 · {{ rev.editor_name }}
          <div class="muted" v-if="rev.reason">修改原因：{{ rev.reason }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { reportApi } from '@/api/reports'
import { statsApi } from '@/api/stats'
import { REPORT_SECTIONS, REPORT_STATUS_MAP, formatDateTime } from '@/utils/dict'
import type { MyHistoryRow, ReportDetail, ReportItem, ReportRevision } from '@/types'

const router = useRouter()
const history = ref<MyHistoryRow[]>([])
const detail = ref<ReportDetail | null>(null)
const revisions = ref<ReportRevision[]>([])
const revisionVisible = ref(false)
const selectedWeek = ref<string>('')

const grouped = computed(() => {
  const map: Record<string, ReportItem[]> = { done: [], progress: [], risk: [], plan: [] }
  for (const item of detail.value?.items ?? []) {
    if (map[item.section]) map[item.section].push(item)
  }
  return map
})

async function loadHistory() {
  history.value = await statsApi.myHistory(26)
}

async function loadDetail(weekStart: string) {
  if (!weekStart) return
  detail.value = await reportApi.mineOfWeek(weekStart).catch(() => null)
}

function viewDetail(row: MyHistoryRow) {
  if (!row.report_id) {
    ElMessage.info('该周没有周报记录')
    return
  }
  router.push({ name: 'report-detail', params: { id: row.report_id } })
}

async function onExport(weekStart: string) {
  await reportApi.exportMy(weekStart)
}

async function loadRevisions() {
  if (!detail.value) return
  revisions.value = await reportApi.revisions(detail.value.id)
  revisionVisible.value = true
}

onMounted(async () => {
  await loadHistory()
  const first = history.value.find((h) => h.report_id)
  if (first) {
    selectedWeek.value = first.week_start
    await loadDetail(first.week_start)
  }
})
</script>

<style scoped>
.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
  font-weight: 600;
}

.content-list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
  color: #1f2937;
}
</style>
