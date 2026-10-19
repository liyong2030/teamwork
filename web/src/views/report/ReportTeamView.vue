<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">周报团队视图</span>
        <div>
          <el-select
            v-model="filterWeek"
            placeholder="选择周"
            style="width: 180px"
            @change="loadAll"
          >
            <el-option v-for="w in weekOptions" :key="w" :label="w" :value="w" />
          </el-select>
          <el-select
            v-model="filterDept"
            placeholder="全部部门"
            clearable
            style="width: 180px; margin-left: 8px"
            @change="loadAll"
          >
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-button style="margin-left: 8px" @click="loadAll">
            <el-icon><Refresh /></el-icon>
          </el-button>
        </div>
      </div>

      <div class="stat-grid" style="margin: 14px 0" v-if="overview">
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
          <div class="mini-value">{{ overview.makeup }}</div>
          <div class="mini-label">补交</div>
        </div>
        <div class="mini-stat">
          <div class="mini-value">{{ overview.by_proxy }}</div>
          <div class="mini-label">代提交</div>
        </div>
        <div class="mini-stat">
          <div class="mini-value">{{ overview.exempt }}</div>
          <div class="mini-label">请假豁免</div>
        </div>
        <div class="mini-stat">
          <div class="mini-value">{{ overview.ontime_rate }}%</div>
          <div class="mini-label">准时率</div>
        </div>
      </div>

      <el-table :data="people" border stripe size="small" v-loading="loading">
        <el-table-column prop="full_name" label="成员" width="120" />
        <el-table-column prop="department_name" label="部门" width="140" />
        <el-table-column label="是否应提交" width="110">
          <template #default="{ row }">
            <el-tag :type="row.required ? 'success' : 'info'" size="small">
              {{ row.required ? '在册' : '豁免' }}
            </el-tag>
            <div v-if="!row.required" class="muted">{{ row.exempt_reason }}</div>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="REPORT_STATUS_MAP[row.status]?.type">{{ row.status_label }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="提交时间" width="180">
          <template #default="{ row }">{{ formatDateTime(row.submitted_at) }}</template>
        </el-table-column>
        <el-table-column label="有效性" width="90">
          <template #default="{ row }">
            <el-tag :type="row.is_valid ? 'success' : 'info'" size="small">
              {{ row.is_valid ? '有效' : '待定' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="连续未交" width="100">
          <template #default="{ row }">
            <span :class="{ 'text-danger': row.continuous_missing >= 2 }">
              {{ row.continuous_missing }} 周
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="180">
          <template #default="{ row }">
            <el-button text type="primary" :disabled="!row.submitted_at" @click="read(row)">
              查看
            </el-button>
            <el-button text type="warning" @click="openProxy(row)">代提交</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-drawer v-model="detailVisible" :title="`${currentName} 的周报`" size="620px">
      <div v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="周次">{{ detail.week_label }}</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.status_label }}</el-descriptions-item>
          <el-descriptions-item label="提交时间">
            {{ formatDateTime(detail.submitted_at) }}
          </el-descriptions-item>
          <el-descriptions-item label="字数">{{ detail.char_count }}</el-descriptions-item>
          <el-descriptions-item label="代提交人" v-if="detail.submitted_by_name">
            {{ detail.submitted_by_name }}（原因：{{ detail.proxy_reason }}）
          </el-descriptions-item>
        </el-descriptions>

        <el-card
          v-for="section in REPORT_SECTIONS"
          :key="section.key"
          shadow="never"
          style="margin-top: 12px"
        >
          <template #header>
            <span class="section-title">{{ section.label }}</span>
          </template>
          <ol v-if="grouped[section.key]?.length" class="content-list">
            <li v-for="item in grouped[section.key]" :key="item.id">{{ item.content }}</li>
          </ol>
          <span v-else class="muted">未填写</span>
        </el-card>

        <el-divider content-position="left">组长批注</el-divider>
        <el-input v-model="reviewComment" type="textarea" :rows="2" placeholder="填写审阅意见" />
        <div style="margin-top: 10px; text-align: right">
          <el-button @click="review(false)">退回重填</el-button>
          <el-button type="primary" @click="review(true)">审阅通过</el-button>
        </div>
      </div>
      <el-empty v-else description="该成员本周暂无周报" />
    </el-drawer>

    <el-dialog v-model="proxyVisible" title="代提交周报" width="640px">
      <el-alert
        type="warning"
        :closable="false"
        title="代提交的周报状态标记为「代提交」，独立成列统计，历史记录保留代提交人与原因。"
        style="margin-bottom: 12px"
      />
      <el-form label-width="90px">
        <el-form-item label="成员">{{ currentName }}</el-form-item>
        <el-form-item label="代提交原因" required>
          <el-input v-model="proxyReason" type="textarea" :rows="2" placeholder="如：成员休假未走审批流程" />
        </el-form-item>
        <el-form-item
          v-for="section in REPORT_SECTIONS"
          :key="section.key"
          :label="section.label"
        >
          <el-input
            v-model="proxyDraft[section.key]"
            type="textarea"
            :rows="2"
            :placeholder="`多条请用换行分隔`"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="proxyVisible = false">取消</el-button>
        <el-button type="primary" :loading="proxySaving" @click="doProxy">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { reportApi } from '@/api/reports'
import { statsApi } from '@/api/stats'
import { mondayOf, REPORT_SECTIONS, REPORT_STATUS_MAP, formatDateTime } from '@/utils/dict'
import type { OverviewData, PeopleRow, ReportDetail, ReportItem } from '@/types'

const loading = ref(false)
const people = ref<PeopleRow[]>([])
const overview = ref<OverviewData | null>(null)
const departments = ref<Array<{ id: number; name: string }>>([])
const filterWeek = ref(mondayOf(new Date()))
const filterDept = ref<number | null>(null)

const detailVisible = ref(false)
const detail = ref<ReportDetail | null>(null)
const currentName = ref('')
const currentUser = ref<number | null>(null)
const reviewComment = ref('')

const proxyVisible = ref(false)
const proxySaving = ref(false)
const proxyReason = ref('')
const proxyDraft = reactive<Record<string, string>>({ done: '', progress: '', risk: '', plan: '' })

const weekOptions = computed(() => {
  const list: string[] = []
  const base = new Date(filterWeek.value)
  for (let i = -1; i <= 8; i++) {
    const d = new Date(base)
    d.setDate(d.getDate() + i * 7)
    list.push(mondayOf(d))
  }
  return list.sort((a, b) => (a < b ? 1 : -1))
})

const grouped = computed(() => {
  const map: Record<string, ReportItem[]> = { done: [], progress: [], risk: [], plan: [] }
  for (const item of detail.value?.items ?? []) {
    if (map[item.section]) map[item.section].push(item)
  }
  return map
})

async function loadAll() {
  loading.value = true
  try {
    const [rows, summary] = await Promise.all([
      statsApi.people({ week_start: filterWeek.value, department_id: filterDept.value ?? undefined }),
      statsApi.overview({ week_start: filterWeek.value, department_id: filterDept.value ?? undefined }),
    ])
    people.value = rows
    overview.value = summary
  } finally {
    loading.value = false
  }
}

async function read(row: PeopleRow) {
  currentName.value = row.full_name
  currentUser.value = row.user_id
  const found = await reportApi
    .list({ user_id: row.user_id, week_start: filterWeek.value })
    .catch(() => [])
  detail.value = found[0] ?? null
  reviewComment.value = detail.value?.review_comment ?? ''
  detailVisible.value = true
}

async function review(approved: boolean) {
  if (!detail.value) return
  await reportApi.review(detail.value.id, approved, reviewComment.value)
  ElMessage.success(approved ? '已审阅通过' : '已退回重填')
  detailVisible.value = false
  await loadAll()
}

function openProxy(row: PeopleRow) {
  currentName.value = row.full_name
  currentUser.value = row.user_id
  proxyReason.value = ''
  Object.keys(proxyDraft).forEach((k) => (proxyDraft[k] = ''))
  proxyVisible.value = true
}

async function doProxy() {
  if (!currentUser.value) return
  if (!proxyReason.value.trim()) {
    ElMessage.warning('请填写代提交原因')
    return
  }
  const items: Array<{ section: string; content: string }> = []
  for (const section of REPORT_SECTIONS) {
    const text = proxyDraft[section.key] ?? ''
    text
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((content) => items.push({ section: section.key, content }))
  }
  if (!items.length) {
    ElMessage.warning('请至少填写一段内容')
    return
  }
  proxySaving.value = true
  try {
    await reportApi.proxySubmit(currentUser.value, items, proxyReason.value, filterWeek.value)
    ElMessage.success('代提交成功')
    proxyVisible.value = false
    await loadAll()
  } finally {
    proxySaving.value = false
  }
}

onMounted(async () => {
  departments.value = await statsApi.departmentOptions().catch(() => [])
  await loadAll()
})
</script>

<style scoped>
.mini-stat {
  background: #f8fafc;
  border-radius: 8px;
  padding: 12px 8px;
  text-align: center;
}

.mini-value {
  font-size: 20px;
  font-weight: 600;
}

.mini-label {
  margin-top: 2px;
  font-size: 12px;
  color: #6b7280;
}

.section-title {
  font-size: 14px;
  font-weight: 600;
}

.content-list {
  margin: 0;
  padding-left: 20px;
  line-height: 1.9;
}
</style>
