<template>
  <div class="page-container">
    <!-- 待我审批：组长/管理员可见，放在最前面 -->
    <div class="page-card" v-if="store.isLeader">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">
          待我审批
          <el-badge
            v-if="pendingForApproval.length"
            :value="pendingForApproval.length"
            type="danger"
            style="margin-left: 8px"
          />
        </span>
        <el-button text @click="loadLeaves">
          <el-icon><Refresh /></el-icon>
          刷新
        </el-button>
      </div>
      <el-alert
        v-if="!pendingForApproval.length"
        type="success"
        :closable="false"
        show-icon
        style="margin: 12px 0"
        title="当前没有待审批的请假申请。"
      />
      <el-table
        v-else
        :data="pendingForApproval"
        border
        stripe
        size="small"
        style="margin-top: 12px"
      >
        <el-table-column label="申请人" width="120">
          <template #default="{ row }">
            {{ row.full_name || row.username }}
          </template>
        </el-table-column>
        <el-table-column label="起止日期" width="200">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column label="天数" width="80">
          <template #default="{ row }">{{ daysBetween(row) }} 天</template>
        </el-table-column>
        <el-table-column prop="reason" label="事由" min-width="160" show-overflow-tooltip />
        <el-table-column label="提交时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button text type="success" :loading="decidingId === row.id" @click="decide(row, true)">
              通过
            </el-button>
            <el-button text type="danger" :loading="decidingId === row.id" @click="decide(row, false)">
              驳回
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 我的请假申请 -->
    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">我的请假申请</span>
        <el-button type="primary" @click="dialogVisible = true">
          <el-icon><Plus /></el-icon>
          提交请假
        </el-button>
      </div>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin: 12px 0"
        title="仅「已通过」的请假会在生成周报点名名册时扣减应提交人数，直接影响提交率分母。"
      />
      <el-table :data="myLeaves" border stripe size="small">
        <el-table-column label="起止日期" width="200">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="事由" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="LEAVE_STATUS_MAP[row.status]?.type">
              {{ LEAVE_STATUS_MAP[row.status]?.label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="审批人" width="120">
          <template #default="{ row }">
            {{ row.approver_name || (row.decided_at ? '已处理' : '待组长审批') }}
          </template>
        </el-table-column>
        <el-table-column label="审批时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.decided_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110">
          <template #default="{ row }">
            <el-button
              text
              type="danger"
              :disabled="!row.can_cancel"
              @click="cancel(row)"
            >
              撤回
            </el-button>
          </template>
        </el-table-column>
        <template #empty>暂无请假记录</template>
      </el-table>
    </div>

    <!-- 团队请假记录（只读） -->
    <div class="page-card" v-if="store.isLeader">
      <span class="page-title">团队请假记录</span>
      <el-table :data="teamLeaves" border stripe size="small" style="margin-top: 12px">
        <el-table-column label="成员" width="120">
          <template #default="{ row }">{{ row.full_name || row.username }}</template>
        </el-table-column>
        <el-table-column label="起止日期" width="200">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="事由" min-width="160" show-overflow-tooltip />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag :type="LEAVE_STATUS_MAP[row.status]?.type">
              {{ LEAVE_STATUS_MAP[row.status]?.label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="审批人" width="120">
          <template #default="{ row }">
            {{ row.approver_name || (row.decided_at ? '已处理' : '待处理') }}
          </template>
        </el-table-column>
        <el-table-column label="审批时间" width="150">
          <template #default="{ row }">{{ formatDateTime(row.decided_at) }}</template>
        </el-table-column>
        <template #empty>暂无其他成员的请假记录</template>
      </el-table>
    </div>

    <!-- 本周豁免名单 -->
    <div class="page-card" v-if="store.isLeader">
      <span class="page-title">本周豁免名单</span>
      <el-select v-model="exemptWeek" style="width: 170px; margin-left: 10px" @change="loadExempt">
        <el-option v-for="w in recentWeeks" :key="w" :label="w" :value="w" />
      </el-select>
      <el-table :data="exempt" border stripe size="small" style="margin-top: 12px">
        <el-table-column prop="full_name" label="成员" width="130" />
        <el-table-column label="请假区间" width="200">
          <template #default="{ row }">{{ row.start_date }} ~ {{ row.end_date }}</template>
        </el-table-column>
        <el-table-column prop="reason" label="事由" min-width="160" />
        <template #empty>该周没有豁免成员</template>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="提交请假" width="480px">
      <el-form label-width="90px">
        <el-form-item label="起止日期" required>
          <el-date-picker
            v-model="range"
            type="daterange"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="请假事由">
          <el-input v-model="reason" type="textarea" :rows="3" placeholder="如：年假 / 病假 / 出差" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submit">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { leaveApi } from '@/api/organization'
import { useUserStore } from '@/stores/user'
import { mondayOf, LEAVE_STATUS_MAP, formatDateTime } from '@/utils/dict'
import type { LeaveItem, WeekExemption } from '@/types'

const store = useUserStore()
const leaves = ref<LeaveItem[]>([])
const exempt = ref<WeekExemption[]>([])
const dialogVisible = ref(false)
const saving = ref(false)
const decidingId = ref<number | null>(null)
const range = ref<[string, string] | null>(null)
const reason = ref('')
const exemptWeek = ref(mondayOf(new Date()))

const myId = computed(() => store.profile?.id ?? -1)
const myLeaves = computed(() => leaves.value.filter((l) => l.user_id === myId.value))
/** 我能审批的：待审批 + 后端判定 can_decide（排除自己的申请） */
const pendingForApproval = computed(() => leaves.value.filter((l) => l.can_decide))
/** 团队内其余记录（别人的、且不需要我处理的），只读展示 */
const teamLeaves = computed(() =>
  leaves.value.filter((l) => l.user_id !== myId.value && !l.can_decide),
)

const recentWeeks = computed(() => {
  const list: string[] = []
  for (let i = 0; i < 8; i++) {
    const d = new Date()
    d.setDate(d.getDate() - i * 7)
    list.push(mondayOf(d))
  }
  return list
})

function daysBetween(row: LeaveItem) {
  const s = new Date(row.start_date).getTime()
  const e = new Date(row.end_date).getTime()
  if (Number.isNaN(s) || Number.isNaN(e)) return '-'
  return Math.floor((e - s) / 86400000) + 1
}

async function loadLeaves() {
  leaves.value = await leaveApi.list({ limit: 200 }).catch(() => [])
}

async function loadExempt() {
  if (!store.isLeader) return
  exempt.value = await leaveApi.weekExemptions(exemptWeek.value).catch(() => [])
}

async function submit() {
  if (!range.value) {
    ElMessage.warning('请选择起止日期')
    return
  }
  saving.value = true
  try {
    await leaveApi.create({
      start_date: range.value[0],
      end_date: range.value[1],
      reason: reason.value || null,
    })
    ElMessage.success('请假已提交，等待组长审批')
    dialogVisible.value = false
    range.value = null
    reason.value = ''
    await loadLeaves()
  } finally {
    saving.value = false
  }
}

async function decide(row: LeaveItem, approved: boolean) {
  let comment: string | undefined
  if (!approved) {
    try {
      const res = await ElMessageBox.prompt(
        `请填写驳回「${row.full_name || row.username}」请假的原因`,
        '驳回请假',
        {
          inputPlaceholder: '如：时间冲突，请改期',
          inputValidator: (v: string) => (v && v.trim().length > 0 ? true : '请填写驳回原因'),
        },
      )
      comment = String(res.value).trim()
    } catch {
      return
    }
  }
  decidingId.value = row.id
  try {
    await leaveApi.decide(row.id, approved, comment)
    ElMessage.success(approved ? '已通过，该成员本周将计入豁免' : '已驳回')
    await Promise.all([loadLeaves(), loadExempt()])
  } finally {
    decidingId.value = null
  }
}

async function cancel(row: LeaveItem) {
  await leaveApi.cancel(row.id)
  ElMessage.success('已撤回')
  await loadLeaves()
}

onMounted(async () => {
  await loadLeaves()
  await loadExempt()
})
</script>
