<template>
  <div class="page-container">
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">周报提交统计看板</span>
        <div>
          <el-select
            v-model="weekStart"
            placeholder="选择周"
            style="width: 170px"
            @change="loadAll"
          >
            <el-option
              v-for="w in weekOptions"
              :key="w"
              :label="w"
              :value="w"
            />
          </el-select>
          <el-select
            v-model="deptId"
            placeholder="全部部门"
            clearable
            style="width: 170px; margin: 0 8px"
            @change="loadAll"
          >
            <el-option v-for="d in departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
          <el-button-group>
            <el-button :loading="exporting.xlsx" @click="doExport('xlsx')">导出 Excel</el-button>
            <el-button :loading="exporting.csv" @click="doExport('csv')">导出 CSV</el-button>
          </el-button-group>
        </div>
      </div>

      <el-alert
        v-if="overview?.finalized"
        type="success"
        :closable="false"
        show-icon
        style="margin-top: 12px"
        :title="`${overview.week_label} 已定版归档，以下为冻结数据，补交不会回填历史。`"
      />

      <div class="stat-grid" style="margin: 14px 0">
        <div class="kpi">
          <div class="kpi-value">{{ overview?.required ?? 0 }}</div>
          <div class="kpi-label">应提交人数</div>
          <div class="kpi-sub">已扣减请假豁免 {{ overview?.exempt ?? 0 }} 人</div>
        </div>
        <div class="kpi">
          <div class="kpi-value text-success">{{ overview?.ontime ?? 0 }}</div>
          <div class="kpi-label">准时</div>
          <div class="kpi-sub">{{ overview?.ontime_rate ?? 0 }}%</div>
        </div>
        <div class="kpi">
          <div class="kpi-value text-warning">{{ overview?.late ?? 0 }}</div>
          <div class="kpi-label">迟到</div>
          <div class="kpi-sub">周五18:00后~周一09:30前</div>
        </div>
        <div class="kpi">
          <div class="kpi-value" style="color: #8e7cfb">{{ overview?.makeup ?? 0 }}</div>
          <div class="kpi-label">补交</div>
          <div class="kpi-sub">定版后补交，独立成列</div>
        </div>
        <div class="kpi">
          <div class="kpi-value text-danger">{{ overview?.missing ?? 0 }}</div>
          <div class="kpi-label">未提交</div>
          <div class="kpi-sub">{{ overview?.missing_rate ?? 0 }}%</div>
        </div>
        <div class="kpi">
          <div class="kpi-value" style="color: #d97706">{{ overview?.by_proxy ?? 0 }}</div>
          <div class="kpi-label">代提交</div>
          <div class="kpi-sub">组长代填，独立成列</div>
        </div>
        <div class="kpi">
          <div class="kpi-value">{{ overview?.submitted ?? 0 }}</div>
          <div class="kpi-label">实际提交</div>
          <div class="kpi-sub">提交率 {{ overview?.submit_rate ?? 0 }}%</div>
        </div>
        <div class="kpi">
          <div class="kpi-value">{{ overview?.valid ?? 0 }}</div>
          <div class="kpi-label">有效周报</div>
          <div class="kpi-sub">有效率 {{ overview?.valid_rate ?? 0 }}%</div>
        </div>
      </div>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="12">
        <div class="page-card">
          <span class="page-title">部门横向对比</span>
          <div ref="deptChartRef" style="height: 300px" />
        </div>
      </el-col>
      <el-col :xs="24" :lg="12">
        <div class="page-card">
          <span class="page-title">近 12 周提交趋势</span>
          <div ref="trendChartRef" style="height: 300px" />
        </div>
      </el-col>
    </el-row>

    <div class="page-card">
      <el-tabs>
        <el-tab-pane label="成员明细">
          <el-table :data="people" border stripe size="small" v-loading="loading">
            <el-table-column prop="full_name" label="成员" width="110" />
            <el-table-column prop="department_name" label="部门" width="130" />
            <el-table-column label="在册" width="80">
              <template #default="{ row }">
                <el-tag :type="row.required ? 'success' : 'info'" size="small">
                  {{ row.required ? '在册' : '豁免' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="REPORT_STATUS_MAP[row.status]?.type">{{ row.status_label }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" width="170">
              <template #default="{ row }">{{ formatDateTime(row.submitted_at) }}</template>
            </el-table-column>
            <el-table-column label="有效性" width="90">
              <template #default="{ row }">
                <el-tag :type="row.is_valid ? 'success' : 'info'" size="small">
                  {{ row.is_valid ? '有效' : '待定' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="连续未交" prop="continuous_missing" width="100">
              <template #default="{ row }">
                <span :class="{ 'text-danger': row.continuous_missing >= 2 }">
                  {{ row.continuous_missing }} 周
                </span>
              </template>
            </el-table-column>
            <el-table-column prop="exempt_reason" label="豁免原因" min-width="140" />
          </el-table>
        </el-tab-pane>
        <el-tab-pane label="定版快照">
          <el-table :data="snapshots" border stripe size="small">
            <el-table-column prop="department_name" label="部门" width="150" />
            <el-table-column prop="week_start" label="周起始" width="120" />
            <el-table-column prop="required_count" label="应提交" width="90" />
            <el-table-column prop="ontime_count" label="准时" width="80" />
            <el-table-column prop="late_count" label="迟到" width="80" />
            <el-table-column prop="makeup_count" label="补交" width="80" />
            <el-table-column prop="missing_count" label="未交" width="80" />
            <el-table-column prop="by_proxy_count" label="代提交" width="90" />
            <el-table-column label="已定版" width="90">
              <template #default="{ row }">
                <el-tag :type="row.finalized ? 'success' : 'info'" size="small">
                  {{ row.finalized ? '已归档' : '未定版' }}
                </el-tag>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as echarts from 'echarts'
import { statsApi } from '@/api/stats'
import { mondayOf, REPORT_STATUS_MAP, formatDateTime } from '@/utils/dict'
import type {
  DepartmentStatRow,
  OverviewData,
  PeopleRow,
  StatSnapshot,
  TrendRow,
} from '@/types'

const loading = ref(false)
const weekStart = ref(mondayOf(new Date()))
const deptId = ref<number | null>(null)
const overview = ref<OverviewData | null>(null)
const deptRows = ref<DepartmentStatRow[]>([])
const trendRows = ref<TrendRow[]>([])
const people = ref<PeopleRow[]>([])
const snapshots = ref<StatSnapshot[]>([])
const departments = ref<Array<{ id: number; name: string }>>([])

const exporting = reactive({ xlsx: false, csv: false })

const deptChartRef = ref<HTMLDivElement>()
const trendChartRef = ref<HTMLDivElement>()
const deptChart = shallowRef<echarts.ECharts>()
const trendChart = shallowRef<echarts.ECharts>()

const weekOptions = computed(() => {
  const list: string[] = []
  const base = new Date()
  for (let i = 0; i < 12; i++) {
    const d = new Date(base)
    d.setDate(d.getDate() - i * 7)
    list.push(mondayOf(d))
  }
  return list
})

async function loadAll() {
  loading.value = true
  try {
    const deptParam = deptId.value ?? undefined
    const [sum, rows, tr, pp, sn] = await Promise.all([
      statsApi.overview({ week_start: weekStart.value, department_id: deptParam }),
      statsApi.departments({ week_start: weekStart.value }),
      statsApi.trend({ weeks: 12, department_id: deptParam }),
      statsApi.people({ week_start: weekStart.value, department_id: deptParam }),
      statsApi.snapshots({ week_start: weekStart.value, department_id: deptParam }),
    ])
    overview.value = sum
    deptRows.value = deptId.value ? rows.filter((r) => r.department_id === deptId.value) : rows
    trendRows.value = tr
    people.value = pp
    snapshots.value = sn
    renderCharts()
  } finally {
    loading.value = false
  }
}

function renderCharts() {
  if (deptChartRef.value) {
    deptChart.value = deptChart.value ?? echarts.init(deptChartRef.value)
    deptChart.value.setOption(
      {
        tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
        legend: { data: ['准时', '迟到', '补交', '未提交'], bottom: 0 },
        grid: { left: 40, right: 16, top: 24, bottom: 46 },
        xAxis: { type: 'category', data: deptRows.value.map((r) => r.department_name) },
        yAxis: { type: 'value' },
        series: [
          { name: '准时', type: 'bar', stack: 'total', itemStyle: { color: '#67c23a' }, data: deptRows.value.map((r) => r.ontime) },
          { name: '迟到', type: 'bar', stack: 'total', itemStyle: { color: '#e6a23c' }, data: deptRows.value.map((r) => r.late) },
          { name: '补交', type: 'bar', stack: 'total', itemStyle: { color: '#8e7cfb' }, data: deptRows.value.map((r) => r.makeup) },
          { name: '未提交', type: 'bar', stack: 'total', itemStyle: { color: '#f56c6c' }, data: deptRows.value.map((r) => r.missing) },
        ],
      },
      true,
    )
  }
  if (trendChartRef.value) {
    trendChart.value = trendChart.value ?? echarts.init(trendChartRef.value)
    trendChart.value.setOption(
      {
        tooltip: { trigger: 'axis', valueFormatter: (v: number) => `${v}%` },
        legend: { data: ['准时率', '提交率'], bottom: 0 },
        grid: { left: 44, right: 16, top: 24, bottom: 46 },
        xAxis: { type: 'category', data: trendRows.value.map((r) => r.week_label ?? r.week_start) },
        yAxis: { type: 'value', max: 100, axisLabel: { formatter: '{value}%' } },
        series: [
          {
            name: '准时率',
            type: 'line',
            smooth: true,
            areaStyle: { opacity: 0.14 },
            itemStyle: { color: '#2f5597' },
            data: trendRows.value.map((r) => r.ontime_rate),
          },
          {
            name: '提交率',
            type: 'line',
            smooth: true,
            areaStyle: { opacity: 0.1 },
            itemStyle: { color: '#67c23a' },
            data: trendRows.value.map((r) => r.submit_rate),
          },
        ],
      },
      true,
    )
  }
}

async function doExport(fmt: 'xlsx' | 'csv') {
  exporting[fmt] = true
  try {
    await statsApi.download(
      { week_start: weekStart.value, department_id: deptId.value, fmt },
      `周报统计_${weekStart.value}.${fmt}`,
    )
  } catch (error) {
    ElMessage.error((error as Error).message || '导出失败')
  } finally {
    exporting[fmt] = false
  }
}

watch(
  () => [weekStart.value, deptId.value],
  () => loadAll(),
)

onMounted(async () => {
  departments.value = await statsApi.departmentOptions().catch(() => [])
  await loadAll()
  window.addEventListener('resize', () => {
    deptChart.value?.resize()
    trendChart.value?.resize()
  })
})
</script>

<style scoped>
.kpi {
  background: #f8fafc;
  border-radius: 8px;
  padding: 14px 12px;
  text-align: center;
}

.kpi-value {
  font-size: 24px;
  font-weight: 600;
  color: #16222f;
}

.kpi-label {
  margin-top: 2px;
  font-size: 13px;
  color: #374151;
}

.kpi-sub {
  margin-top: 2px;
  font-size: 11px;
  color: #9ca3af;
}
</style>
