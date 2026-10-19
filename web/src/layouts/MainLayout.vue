<template>
  <el-container class="layout-root">
    <el-aside :width="collapsed ? '64px' : '220px'" class="layout-aside">
      <div class="brand">
        <el-icon :size="22" color="#fff"><Connection /></el-icon>
        <span v-show="!collapsed" class="brand-text">团队协同管理平台</span>
      </div>
      <el-scrollbar>
        <el-menu
          :default-active="activeMenu"
          :collapse="collapsed"
          :collapse-transition="false"
          background-color="#1f2d3d"
          text-color="#c3cbd8"
          active-text-color="#ffd04b"
          router
        >
          <template v-for="item in menus" :key="item.path">
            <el-menu-item v-if="!item.hidden" :index="item.path">
              <el-icon><component :is="item.icon" /></el-icon>
              <template #title>{{ item.title }}</template>
            </el-menu-item>
          </template>
        </el-menu>
      </el-scrollbar>
    </el-aside>

    <el-container>
      <el-header class="layout-header">
        <div class="header-left">
          <el-button text @click="collapsed = !collapsed">
            <el-icon :size="18">
              <component :is="collapsed ? 'Expand' : 'Fold'" />
            </el-icon>
          </el-button>
          <el-breadcrumb separator="/">
            <el-breadcrumb-item :to="{ path: '/dashboard' }">首页</el-breadcrumb-item>
            <el-breadcrumb-item v-if="route.meta.title">{{ route.meta.title }}</el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <el-badge :value="unread" :hidden="!unread" :max="99">
            <el-button text circle @click="router.push({ name: 'notifications' })">
              <el-icon :size="18"><Bell /></el-icon>
            </el-button>
          </el-badge>
          <el-dropdown trigger="click" @command="onCommand">
            <span class="user-entry">
              <el-avatar :size="28" :style="{ background: '#2f5597' }">
                {{ displayName.slice(0, 1) }}
              </el-avatar>
              <span class="user-name">{{ displayName }}</span>
              <el-icon><ArrowDown /></el-icon>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="profile">个人资料</el-dropdown-item>
                <el-dropdown-item command="password">修改密码</el-dropdown-item>
                <el-dropdown-item command="logout" divided>退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="layout-main">
        <router-view v-slot="{ Component }">
          <transition name="fade-slide" mode="out-in">
            <component :is="Component" />
          </transition>
        </router-view>
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'
import { authApi } from '@/api/auth'
import { systemApi } from '@/api/system'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const collapsed = ref(false)
const unread = ref(0)

const displayName = computed(() => store.displayName)

interface MenuItem {
  path: string
  title: string
  icon: string
  hidden?: boolean
  admin?: boolean
  leader?: boolean
}

const menus = computed<MenuItem[]>(() => {
  const parent = router.options.routes.find((r) => r.path === '/')
  const children = parent?.children ?? []
  const list: MenuItem[] = []
  for (const child of children) {
    if (child.meta?.hidden) continue
    if (child.meta?.admin && !store.isAdmin) continue
    if (child.meta?.roles && !store.isLeader) continue
    list.push({
      path: `/${child.path}`,
      title: String(child.meta?.title ?? child.name ?? ''),
      icon: String(child.meta?.icon ?? 'Menu'),
    })
  }
  return list
})

const activeMenu = computed(() => {
  const full = route.fullPath
  const matched = menus.value.filter((m) => full.startsWith(m.path))
  return matched.length ? matched[matched.length - 1].path : route.path
})

async function loadUnread() {
  try {
    const data = await systemApi.unreadCount()
    unread.value = data.count
  } catch {
    unread.value = 0
  }
}

async function onCommand(command: string) {
  if (command === 'logout') {
    await ElMessageBox.confirm('确认退出登录？', '提示', { type: 'warning' })
    try {
      await authApi.logout()
    } catch {
      /* 忽略登出失败，本地仍需清理 */
    }
    store.logout()
    router.push({ name: 'login' })
    return
  }
  if (command === 'password') {
    router.push({ name: 'change-password' })
    return
  }
  ElMessage.info('个人资料功能请在「后台管理-用户管理」中由管理员维护')
}

watch(() => route.fullPath, loadUnread)
onMounted(loadUnread)
</script>

<style scoped>
.layout-root {
  height: 100%;
}

.layout-aside {
  background: #1f2d3d;
  transition: width 0.2s ease;
  overflow: hidden;
}

.brand {
  height: 56px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 16px;
  color: #fff;
  background: #16222f;
  white-space: nowrap;
}

.brand-text {
  font-size: 15px;
  font-weight: 600;
}

.layout-header {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.08);
  padding: 0 16px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-entry {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  outline: none;
}

.user-name {
  font-size: 14px;
  color: #1f2937;
}

.layout-main {
  padding: 0;
  background: var(--ctms-bg);
  overflow: auto;
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.18s ease;
}

.fade-slide-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}
</style>
