export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/preconsult/index',
    'pages/knowledge/index',
    'pages/mine/index',
    'pages/disease-detail/index',
    'pages/drug-detail/index',
    'pages/report/index',
    'pages/followup/index'
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#0e7490',
    navigationBarTitleText: '肿瘤健康助手',
    navigationBarTextStyle: 'white',
    backgroundColor: '#f2f7f9'
  },
  tabBar: {
    color: '#7b9099',
    selectedColor: '#0e7490',
    backgroundColor: '#ffffff',
    borderStyle: 'white',
    list: [
      {
        pagePath: 'pages/index/index',
        text: '首页',
        iconPath: 'assets/tabbar/home.svg',
        selectedIconPath: 'assets/tabbar/home-selected.svg'
      },
      {
        pagePath: 'pages/preconsult/index',
        text: '问症状',
        iconPath: 'assets/tabbar/preconsult.svg',
        selectedIconPath: 'assets/tabbar/preconsult-selected.svg'
      },
      {
        pagePath: 'pages/knowledge/index',
        text: '知识',
        iconPath: 'assets/tabbar/knowledge.svg',
        selectedIconPath: 'assets/tabbar/knowledge-selected.svg'
      },
      {
        pagePath: 'pages/mine/index',
        text: '我的',
        iconPath: 'assets/tabbar/mine.svg',
        selectedIconPath: 'assets/tabbar/mine-selected.svg'
      }
    ]
  }
})
