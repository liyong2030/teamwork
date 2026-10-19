import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api/auth'
import { useUserStore } from '@/stores/user'

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/LoginView.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/change-password',
    name: 'change-password',
    component: () => import('@/views/ChangePasswordView.vue'),
    meta: { title: '修改密码' },
  },
  {
    path: '/',
    component: () => import('@/layouts/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('@/views/DashboardView.vue'),
        meta: { title: '工作台', icon: 'Odometer' },
      },
      {
        path: 'reports/write',
        name: 'report-write',
        component: () => import('@/views/report/ReportWriteView.vue'),
        meta: { title: '填写周报', icon: 'EditPen' },
      },
      {
        path: 'reports/history',
        name: 'report-history',
        component: () => import('@/views/report/ReportHistoryView.vue'),
        meta: { title: '我的周报', icon: 'Document' },
      },
      {
        path: 'reports/team',
        name: 'report-team',
        component: () => import('@/views/report/ReportTeamView.vue'),
        meta: { title: '团队周报', icon: 'Files', roles: ['leader', 'admin'] },
      },
      {
        path: 'reports/detail/:id',
        name: 'report-detail',
        component: () => import('@/views/report/ReportDetailView.vue'),
        meta: { title: '周报详情', hidden: true },
      },
      {
        path: 'tasks',
        name: 'task-list',
        component: () => import('@/views/task/TaskListView.vue'),
        meta: { title: '任务列表', icon: 'List' },
      },
      {
        path: 'projects',
        name: 'project-list',
        component: () => import('@/views/project/ProjectListView.vue'),
        meta: { title: '项目看板', icon: 'Grid' },
      },
      {
        path: 'projects/:id',
        name: 'project-detail',
        component: () => import('@/views/project/ProjectBoardView.vue'),
        meta: { title: '项目详情', hidden: true },
      },
      {
        path: 'stats',
        name: 'stats',
        component: () => import('@/views/StatsView.vue'),
        meta: { title: '统计看板', icon: 'DataAnalysis', roles: ['leader', 'admin'] },
      },
      {
        path: 'leaves',
        name: 'leaves',
        component: () => import('@/views/LeaveView.vue'),
        meta: { title: '请假豁免', icon: 'Calendar' },
      },
      {
        path: 'notifications',
        name: 'notifications',
        component: () => import('@/views/NotificationView.vue'),
        meta: { title: '消息中心', icon: 'Bell' },
      },
      {
        path: 'admin/users',
        name: 'admin-users',
        component: () => import('@/views/admin/UserManageView.vue'),
        meta: { title: '用户管理', icon: 'User', admin: true },
      },
      {
        path: 'admin/departments',
        name: 'admin-departments',
        component: () => import('@/views/admin/DepartmentManageView.vue'),
        meta: { title: '部门管理', icon: 'OfficeBuilding', admin: true },
      },
      {
        path: 'admin/system',
        name: 'admin-system',
        component: () => import('@/views/admin/SystemSettingView.vue'),
        meta: { title: '系统设置', icon: 'Setting', admin: true },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'not-found',
    component: () => import('@/views/NotFoundView.vue'),
    meta: { public: true },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
})

router.beforeEach(async (to) => {
  const store = useUserStore()
  const token = store.accessToken

  if (to.meta.public) {
    return true
  }
  if (!token) {
    return { name: 'login', query: { redirect: to.fullPath } }
  }
  if (!store.profile) {
    try {
      await authApi.me().then((data) => store.setProfile(data))
    } catch {
      store.logout()
      return { name: 'login', query: { redirect: to.fullPath } }
    }
  }
  const profile = store.profile!
  // 首次登录强制改密：除改密页与登录页外一律拦截
  if (profile.must_change_password && to.name !== 'change-password') {
    ElMessage.warning('首次登录请先修改密码')
    return { name: 'change-password' }
  }
  if (to.meta.admin && !profile.is_superuser) {
    ElMessage.error('仅管理员可访问该页面')
    return { name: 'dashboard' }
  }
  if (to.meta.roles && !profile.is_superuser) {
    const isLeader = profile.is_department_leader
    if (!isLeader) {
      ElMessage.error('仅组长或管理员可访问该页面')
      return { name: 'dashboard' }
    }
  }
  document.title = to.meta.title ? `${to.meta.title} - 团队协同管理平台` : '团队协同管理平台'
  return true
})

export default router
