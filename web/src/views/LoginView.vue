<template>
  <div class="login-page">
    <div class="login-box">
      <div class="login-brand">
        <el-icon :size="30" color="#2f5597"><Connection /></el-icon>
        <h1>团队协同管理平台</h1>
        <p>周报自动化 · 任务闭环 · 提交统计</p>
      </div>
      <el-alert
        v-if="sso.enabled"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
        :title="`本系统已接入${sso.label}`"
        :description="sso.default ? '默认使用统一身份认证账号登录' : '可在下方选择登录方式'"
      />

      <el-radio-group
        v-if="sso.enabled && !sso.default"
        v-model="mode"
        size="small"
        style="margin-bottom: 14px; display: flex"
      >
        <el-radio-button value="local">本地口令</el-radio-button>
        <el-radio-button value="sso">{{ sso.label }}</el-radio-button>
      </el-radio-group>

      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="onSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="登录名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            placeholder="密码"
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-button type="primary" class="login-btn" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>
      <div class="login-tip">
        <template v-if="sso.enabled && (sso.default || mode === 'sso')">
          请使用{{ sso.label }}的账号与口令登录，凭据由后端提交给认证系统校验，不在本系统保存。
        </template>
        <template v-else>
          初始账号由管理员通过
          <code>create-admin</code>
          脚本生成，初始密码仅打印一次。首次登录需强制修改密码。
        </template>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import { authApi, type SsoConfig } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const route = useRoute()
const store = useUserStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
const form = ref({ username: '', password: '' })
const sso = ref<SsoConfig>({ enabled: false, default: false, label: '统一身份认证', provider: null, auth_source: null, choices: [] })
const mode = ref<'local' | 'sso'>('local')

const rules: FormRules = {
  username: [{ required: true, message: '请输入登录名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

onMounted(async () => {
  // 登录页是匿名入口，取不到配置就退化成本地口令登录，不影响可用性
  sso.value = await authApi.ssoConfig().catch(() => sso.value)
  mode.value = sso.value.enabled && sso.value.default ? 'sso' : 'local'
})

function errorCodeOf(err: unknown): string {
  const data = (err as { response?: { data?: { code?: string } } })?.response?.data
  return data?.code || ''
}

async function onSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    let token
    if (mode.value === 'sso') {
      token = await authApi.ssoLogin(form.value)
    } else {
      // 静默尝试本地口令：若该账号已接入统一身份认证，自动改走 IdP 校验，
      // 用户只需输入一次账号密码，不需要先猜自己该用哪种方式。
      token = await authApi.login(form.value, true).catch(async (err: unknown) => {
        if (errorCodeOf(err) === 'sso_required' && sso.value.enabled) {
          return authApi.ssoLogin(form.value)
        }
        throw err
      })
    }
    store.setTokens(token.access_token, token.refresh_token)
    const profile = await authApi.me()
    store.setProfile(profile)
    if (profile.must_change_password) {
      ElMessage.warning('首次登录，请先修改密码')
      router.push({ name: 'change-password' })
      return
    }
    const redirect = route.query.redirect as string | undefined
    router.push(redirect || { name: 'dashboard' })
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f3b6f 0%, #2f5597 55%, #4a7cc7 100%);
}

.login-box {
  width: 400px;
  padding: 36px 36px 24px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.22);
}

.login-brand {
  text-align: center;
  margin-bottom: 24px;
}

.login-brand h1 {
  font-size: 20px;
  margin: 10px 0 4px;
  color: #16222f;
}

.login-brand p {
  margin: 0;
  color: #6b7280;
  font-size: 13px;
}

.login-btn {
  width: 100%;
}

.login-tip {
  margin-top: 18px;
  font-size: 12px;
  color: #6b7280;
  line-height: 1.7;
  text-align: center;
}

.login-tip code {
  background: #f1f5f9;
  padding: 1px 4px;
  border-radius: 3px;
}
</style>
