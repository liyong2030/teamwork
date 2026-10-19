<template>
  <div class="page-container">
    <div class="page-card">
      <span class="page-title">系统信息</span>
      <el-descriptions :column="4" border size="small" v-if="info">
        <el-descriptions-item label="应用名称">{{ info.app_name }}</el-descriptions-item>
        <el-descriptions-item label="运行环境">{{ info.env }}</el-descriptions-item>
        <el-descriptions-item label="时区">{{ info.timezone }}</el-descriptions-item>
        <el-descriptions-item label="周报截止">{{ info.deadline }}</el-descriptions-item>
        <el-descriptions-item label="核算定版">{{ info.finalize }}</el-descriptions-item>
        <el-descriptions-item label="有效字数下限">{{ info.valid_min_chars }} 字</el-descriptions-item>
        <el-descriptions-item label="定时任务">
          <el-tag :type="info.scheduler_enabled ? 'success' : 'info'" size="small">
            {{ info.scheduler_enabled ? '已启用' : '未启用' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="邮件服务">
          <el-tag :type="info.email_enabled ? 'success' : 'info'" size="small">
            {{ info.email_enabled ? '已启用' : '未启用' }}
          </el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </div>

    <el-row :gutter="16">
      <el-col :xs="24" :lg="14">
        <div class="page-card">
          <span class="page-title">配置项</span>
          <el-table :data="settings" border stripe size="small" v-loading="loading">
            <el-table-column prop="key" label="键" width="220" />
            <el-table-column prop="description" label="说明" min-width="180" />
            <el-table-column label="值" width="220">
              <template #default="{ row }">
                <el-input v-model="row.value" size="small" @blur="save(row)" />
              </template>
            </el-table-column>
          </el-table>
          <el-alert
            type="info"
            :closable="false"
            style="margin-top: 12px"
            title="鼠标移出输入框即自动保存。留值规则：布尔类配置填 true / false，时间类配置填 HH:MM。"
          />
        </div>
      </el-col>

      <el-col :xs="24" :lg="10">
        <div class="page-card">
          <span class="page-title">定时任务</span>
          <el-alert
            type="warning"
            :closable="false"
            style="margin-bottom: 12px"
            title="手动触发仅用于排障与补跑；生产环境由调度器按时点自动执行。"
          />
          <div class="job-list">
            <div v-for="job in jobs" :key="job.id" class="job-row">
              <div>
                <div class="job-name">{{ job.name }}</div>
                <div class="muted">{{ job.id }} · {{ job.desc }}</div>
              </div>
              <el-button size="small" :loading="running === job.id" @click="run(job)">
                立即执行
              </el-button>
            </div>
          </div>
        </div>

        <div class="page-card">
          <span class="page-title">邮件连通性测试</span>
          <div class="email-test">
            <el-input v-model="testEmail" placeholder="接收测试邮件的邮箱" />
            <el-button type="primary" :loading="testing" @click="testMail">发送测试</el-button>
          </div>
        </div>
      </el-col>
    </el-row>

    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">统一身份认证（SSO）</span>
        <div class="sso-head">
          <el-tag :type="ssoTag.type" size="small">{{ ssoTag.text }}</el-tag>
          <el-button size="small" :loading="checking" :disabled="!sso?.enabled" @click="checkSso">
            <el-icon><Connection /></el-icon>连通性自检
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="sso && !sso.enabled"
        type="info"
        :closable="false"
        style="margin-top: 12px"
        title="当前未启用统一身份认证，登录页只显示本地账号口令入口"
        description="启用方式：在 server/.env 中把 AUTH_SSO_ENABLED 改为 true，按所选协议补齐 CAS_* / OIDC_* / LDAP_* 参数，然后重启后端（Docker 部署执行 docker compose restart server）。"
      />

      <template v-else-if="sso">
        <el-descriptions :column="4" border size="small" style="margin-top: 12px">
          <el-descriptions-item label="认证协议">{{ protocolLabel }}</el-descriptions-item>
          <el-descriptions-item label="登录入口名称">{{ sso.label }}</el-descriptions-item>
          <el-descriptions-item label="默认登录方式">
            <el-tag size="small" :type="sso.default ? 'success' : 'info'">
              {{ sso.default ? '统一身份认证' : '按账号认证来源' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="同名账号自动绑定">
            <el-tag size="small" :type="sso.bind_existing ? 'success' : 'info'">
              {{ sso.bind_existing ? '开启' : '关闭' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="未登记账号自动建号">
            <el-tag size="small" :type="sso.auto_create ? 'success' : 'info'">
              {{ sso.auto_create ? '开启' : '关闭' }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="应急通道" :span="3">
            <span class="muted">超级管理员始终用本地口令登录，不会被自动绑定</span>
          </el-descriptions-item>
        </el-descriptions>

        <el-table :data="configRows" border stripe size="small" style="margin-top: 12px">
          <el-table-column prop="label" label="配置项" width="180" />
          <el-table-column label="当前值" min-width="260">
            <template #default="{ row }">
              <span :class="{ muted: row.empty }">{{ row.value }}</span>
            </template>
          </el-table-column>
          <el-table-column label="对应环境变量" width="240">
            <template #default="{ row }">
              <span class="muted">{{ row.env }}</span>
            </template>
          </el-table-column>
        </el-table>

        <el-alert
          v-if="checkResult"
          :type="checkResult.healthy ? 'success' : 'error'"
          :closable="false"
          style="margin-top: 12px"
          :title="`自检结果：${checkResult.healthy ? '连通正常' : '存在异常'} —— ${checkResult.message}`"
          :description="`自检时间：${checkedAt}。自检只做配置完整性与可达性判断，不会发起真实认证，也不会把口令送往 IdP。`"
        />
        <el-alert
          v-else
          type="info"
          :closable="false"
          style="margin-top: 12px"
          title="以上参数来自服务端环境变量，此处只读展示，便于排查"
          description="修改 server/.env 后需重启后端才会生效；账号与 IdP 的绑定关系请到「用户管理」逐人维护。"
        />
      </template>
    </div>

    <div class="page-card">
      <div class="flex-between">
        <span class="page-title" style="margin: 0">审计日志</span>
        <el-button @click="loadLogs"><el-icon><Refresh /></el-icon></el-button>
      </div>
      <el-table :data="logs" border stripe size="small" style="margin-top: 12px">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column prop="actor_name" label="操作人" width="120" />
        <el-table-column prop="action" label="动作" width="180" />
        <el-table-column label="对象" width="180">
          <template #default="{ row }">
            {{ row.target_type }}#{{ row.target_id }}
          </template>
        </el-table-column>
        <el-table-column label="IP" prop="ip_address" width="140" />
        <el-table-column label="详情" min-width="160">
          <template #default="{ row }">
            <span class="muted">{{ JSON.stringify(row.detail) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { systemApi } from '@/api/system'
import { formatDateTime } from '@/utils/dict'
import type { AuditLogItem, SettingItem, SsoStatus, SystemInfo } from '@/types'

const loading = ref(false)
const running = ref('')
const testing = ref(false)
const info = ref<SystemInfo | null>(null)
const settings = ref<SettingItem[]>([])
const logs = ref<AuditLogItem[]>([])
const testEmail = ref('')

// ---------------------------------------------------------------- 统一身份认证
const sso = ref<SsoStatus | null>(null)
const checking = ref(false)
const checkResult = ref<SsoStatus | null>(null)
const checkedAt = ref('')

const PROVIDER_LABELS: Record<string, string> = {
  cas: 'CAS',
  oidc: 'OIDC',
  ldap: 'LDAP / AD',
  saml: 'SAML',
}

/** 配置项的中文名与对应的环境变量名（值与后端 describe() 字段一一对应） */
const CONFIG_META: Record<string, { label: string; env: string }> = {
  server_url: { label: 'CAS 服务地址', env: 'CAS_SERVER_URL' },
  rest_path: { label: 'CAS REST 路径', env: 'CAS_REST_PATH' },
  service_url: { label: 'service 回跳地址', env: 'CAS_SERVICE_URL' },
  require_service_ticket: { label: '强制 service 校验', env: 'CAS_REQUIRE_SERVICE_TICKET' },
  issuer: { label: 'Issuer', env: 'OIDC_ISSUER' },
  token_endpoint: { label: '令牌端点', env: 'OIDC_TOKEN_ENDPOINT' },
  userinfo_endpoint: { label: '用户信息端点', env: 'OIDC_USERINFO_ENDPOINT' },
  scope: { label: 'Scope', env: 'OIDC_SCOPE' },
  client_id: { label: 'Client ID', env: 'OIDC_CLIENT_ID' },
  client_secret: { label: 'Client Secret', env: 'OIDC_CLIENT_SECRET' },
  server_uri: { label: 'LDAP 服务地址', env: 'LDAP_SERVER_URI' },
  base_dn: { label: 'Base DN', env: 'LDAP_BASE_DN' },
  user_filter: { label: '用户过滤器', env: 'LDAP_USER_FILTER' },
  bind_dn_template: { label: 'Bind DN 模板', env: 'LDAP_BIND_DN_TEMPLATE' },
  use_ssl: { label: '启用 SSL/TLS', env: 'LDAP_USE_SSL' },
  search_bind_dn: { label: '搜索账号 DN', env: 'LDAP_SEARCH_BIND_DN' },
}

const protocolLabel = computed(() => {
  const provider = sso.value?.config?.provider
  if (typeof provider !== 'string' || !provider) return '—'
  return PROVIDER_LABELS[provider] ?? provider
})

const ssoTag = computed(() => {
  if (!sso.value?.enabled) return { type: 'info' as const, text: '未启用' }
  if (checkResult.value?.healthy === true) return { type: 'success' as const, text: '自检正常' }
  if (checkResult.value?.healthy === false) return { type: 'danger' as const, text: '自检异常' }
  return { type: 'success' as const, text: '已启用' }
})

const configRows = computed(() => {
  const cfg = sso.value?.config ?? {}
  const rows = Object.entries(CONFIG_META)
    .filter(([key]) => key in cfg)
    .map(([key, meta]) => ({ key, ...meta, raw: cfg[key] }))
  // 后端将来新增的字段也不能被吞掉，兜底显示原始键名
  for (const [key, raw] of Object.entries(cfg)) {
    if (key === 'provider' || key === 'source' || key in CONFIG_META) continue
    rows.push({ key, label: key, env: '—', raw })
  }
  return rows.map((row) => {
    const empty = row.raw === null || row.raw === undefined || row.raw === ''
    return { label: row.label, env: row.env, empty, value: empty ? '未配置' : formatValue(row.raw) }
  })
})

function formatValue(raw: unknown): string {
  if (typeof raw === 'boolean') return raw ? '是' : '否'
  if (raw === '***') return '已配置（内容隐藏）'
  return String(raw)
}

const jobs = [
  { id: 'roll_call', name: '生成本周点名名册（周一 00:05）', desc: '按在册成员 + 请假豁免重建名单' },
  { id: 'remind_fri_1000', name: '周五首次提醒（周五 10:00）', desc: '提示今日 18:00 截止' },
  { id: 'remind_fri_1700', name: '周五截止预警（周五 17:00）', desc: '仅推送未填写且草稿为空的成员' },
  { id: 'remind_sun_2000', name: '周末催办（周日 20:00）', desc: '站内 + 邮件二次催办' },
  { id: 'remind_mon_0830', name: '周一最后通牒（周一 08:30）', desc: '并抄送直属组长' },
  { id: 'finalize', name: '周一定版结算（周一 09:30）', desc: '冻结本周统计结果并推送摘要' },
]

async function loadSettings() {
  loading.value = true
  try {
    settings.value = await systemApi.settings()
  } finally {
    loading.value = false
  }
}

async function loadLogs() {
  logs.value = await systemApi.auditLogs({ limit: 100 }).catch(() => [])
}

async function save(row: SettingItem) {
  await systemApi.updateSetting(row.key, row.value)
  ElMessage.success('配置已保存')
}

async function run(job: { id: string }) {
  running.value = job.id
  try {
    const res = await systemApi.runJob(job.id)
    ElMessage.success(res.message || '任务已触发')
  } finally {
    running.value = ''
  }
}

async function testMail() {
  if (!testEmail.value.trim()) {
    ElMessage.warning('请填写接收邮箱')
    return
  }
  testing.value = true
  try {
    await systemApi.testEmail(testEmail.value)
    ElMessage.success('测试邮件已发送')
  } finally {
    testing.value = false
  }
}

async function checkSso() {
  checking.value = true
  try {
    const res = await systemApi.ssoStatus()
    checkResult.value = res
    checkedAt.value = formatDateTime(new Date().toISOString())
    if (res.enabled) {
      const ok = res.healthy
      const text = `${ok ? '连通正常' : '存在异常'}：${res.message}`
      ok ? ElMessage.success(text) : ElMessage.warning(text)
    } else {
      ElMessage.info(res.message)
    }
  } catch {
    // 全局拦截器已提示错误详情
  } finally {
    checking.value = false
  }
}

onMounted(async () => {
  info.value = await systemApi.info().catch(() => null)
  sso.value = await systemApi.ssoStatus().catch(() => null)
  await loadSettings()
  await loadLogs()
})
</script>

<style scoped>
.job-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.job-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid #eef2f7;
  border-radius: 6px;
}

.job-name {
  font-size: 13px;
  font-weight: 600;
}

.email-test {
  display: flex;
  gap: 8px;
}

.sso-head {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
