#!/bin/bash
# Web Frontend Diagnostic Script
# 用于诊断移动端导航栏问题

echo "========================================"
echo "   Web Frontend 全面诊断脚本"
echo "   $(date)"
echo "========================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 自动检测项目路径
POSSIBLE_PATHS=(
    "/home/linuxuser/nautilus_AlgVex"
    "/home/linuxuser/AlgVex"
    "/home/user/AlgVex"
    "/var/www/AlgVex"
    "$(pwd)"
)

PROJECT_PATH=""
for path in "${POSSIBLE_PATHS[@]}"; do
    if [ -d "$path/web/frontend" ]; then
        PROJECT_PATH="$path"
        break
    fi
done

if [ -z "$PROJECT_PATH" ]; then
    echo -e "${RED}[ERROR] 找不到项目目录！${NC}"
    echo "请手动设置: export PROJECT_PATH=/your/project/path"
    echo ""
    echo "搜索 web/frontend 目录..."
    find /home -name "frontend" -type d 2>/dev/null | grep -E "web/frontend$" | head -5
    exit 1
fi

FRONTEND_PATH="$PROJECT_PATH/web/frontend"
HEADER_FILE="$FRONTEND_PATH/components/layout/header.tsx"

echo -e "${BLUE}[1/8] 项目路径${NC}"
echo "----------------------------------------"
echo "项目目录: $PROJECT_PATH"
echo "前端目录: $FRONTEND_PATH"
echo "Header 文件: $HEADER_FILE"
echo ""

# 检查 header.tsx 是否存在
if [ ! -f "$HEADER_FILE" ]; then
    echo -e "${RED}[ERROR] header.tsx 不存在！${NC}"
    exit 1
fi

echo -e "${BLUE}[2/8] Git 状态${NC}"
echo "----------------------------------------"
cd "$PROJECT_PATH"
echo "当前分支: $(git branch --show-current 2>/dev/null || echo 'N/A')"
echo ""
echo "最近 5 次提交:"
git log --oneline -5 2>/dev/null || echo "无法获取 git 信息"
echo ""
echo "本地修改:"
git status --short 2>/dev/null || echo "N/A"
echo ""

echo -e "${BLUE}[3/8] 检查 header.tsx 关键代码${NC}"
echo "----------------------------------------"

# 检查 header 的 className
echo "Header 元素的 className:"
grep -n "className.*fixed.*top" "$HEADER_FILE" | head -3
echo ""

# 检查是否有问题的 left-1/2 定位
if grep -q "left-1/2.*-translate-x-1/2.*w-auto" "$HEADER_FILE"; then
    echo -e "${RED}[PROBLEM] 发现问题代码: left-1/2 -translate-x-1/2 w-auto${NC}"
    echo "这会导致移动端 header 收缩！"
    grep -n "left-1/2" "$HEADER_FILE"
else
    echo -e "${GREEN}[OK] 没有发现 left-1/2 问题代码${NC}"
fi
echo ""

# 检查是否有正确的 left-4 right-4 定位
if grep -q "left-4 right-4" "$HEADER_FILE"; then
    echo -e "${GREEN}[OK] 发现正确代码: left-4 right-4 (全宽)${NC}"
else
    echo -e "${YELLOW}[WARNING] 没有发现 left-4 right-4 代码${NC}"
fi
echo ""

# 检查 container mx-auto 问题
if grep -q "container mx-auto" "$HEADER_FILE"; then
    echo -e "${YELLOW}[WARNING] 发现 container mx-auto，可能导致移动端问题${NC}"
    grep -n "container mx-auto" "$HEADER_FILE"
else
    echo -e "${GREEN}[OK] 没有 container mx-auto 包装${NC}"
fi
echo ""

echo -e "${BLUE}[4/8] Header 结构分析${NC}"
echo "----------------------------------------"
echo "开头 30 行 (return 语句附近):"
grep -n "return\|<header\|<div.*bg-background\|<div.*flex.*h-14" "$HEADER_FILE" | head -10
echo ""

# 统计 div 标签
OPEN_DIVS=$(grep -o '<div' "$HEADER_FILE" | wc -l)
CLOSE_DIVS=$(grep -o '</div>' "$HEADER_FILE" | wc -l)
echo "Div 标签统计: 开启 $OPEN_DIVS 个, 关闭 $CLOSE_DIVS 个"
if [ "$OPEN_DIVS" -eq "$CLOSE_DIVS" ]; then
    echo -e "${GREEN}[OK] Div 标签数量匹配${NC}"
else
    DIFF=$((OPEN_DIVS - CLOSE_DIVS))
    echo -e "${RED}[PROBLEM] Div 标签不匹配! 差异: $DIFF${NC}"
fi
echo ""

echo -e "${BLUE}[5/8] 前端构建状态${NC}"
echo "----------------------------------------"
cd "$FRONTEND_PATH"

# 检查 .next 目录
if [ -d ".next" ]; then
    echo -e "${GREEN}[OK] .next 构建目录存在${NC}"
    echo "构建时间: $(stat -c %y .next 2>/dev/null || stat -f %Sm .next 2>/dev/null || echo 'N/A')"

    # 检查构建产物中的 header
    if [ -d ".next/static" ]; then
        echo "静态资源大小: $(du -sh .next/static 2>/dev/null | cut -f1)"
    fi
else
    echo -e "${RED}[PROBLEM] .next 目录不存在，前端未构建！${NC}"
fi
echo ""

# 检查 node_modules
if [ -d "node_modules" ]; then
    echo -e "${GREEN}[OK] node_modules 存在${NC}"
else
    echo -e "${RED}[PROBLEM] node_modules 不存在，需要运行 npm install${NC}"
fi
echo ""

echo -e "${BLUE}[6/8] Node/NPM 版本${NC}"
echo "----------------------------------------"
echo "Node 版本: $(node -v 2>/dev/null || echo 'N/A')"
echo "NPM 版本: $(npm -v 2>/dev/null || echo 'N/A')"
echo ""

echo -e "${BLUE}[7/8] 进程状态${NC}"
echo "----------------------------------------"
echo "Next.js 进程:"
ps aux | grep -E "next|node.*frontend" | grep -v grep | head -5 || echo "没有找到运行的进程"
echo ""
echo "Systemd 服务状态:"
systemctl is-active algvex-frontend 2>/dev/null && echo "algvex-frontend: active" || echo "algvex-frontend: inactive"
systemctl is-active algvex-backend 2>/dev/null && echo "algvex-backend: active" || echo "algvex-backend: inactive"
echo ""

echo -e "${BLUE}[8/8] 输出 header.tsx 关键部分${NC}"
echo "----------------------------------------"
echo "Header return 语句 (前 40 行):"
echo "---"
sed -n '/return (/,/^  );$/p' "$HEADER_FILE" | head -40
echo "---"
echo ""

echo "========================================"
echo "   诊断完成"
echo "========================================"
echo ""

# 总结问题
echo -e "${YELLOW}问题总结:${NC}"
echo "----------------------------------------"

ISSUES=0

if grep -q "left-1/2.*-translate-x-1/2" "$HEADER_FILE"; then
    echo -e "${RED}1. Header 使用了 left-1/2 居中定位，导致移动端收缩${NC}"
    ISSUES=$((ISSUES + 1))
fi

if grep -q "container mx-auto" "$HEADER_FILE"; then
    echo -e "${YELLOW}2. 存在 container mx-auto 包装，可能影响移动端${NC}"
    ISSUES=$((ISSUES + 1))
fi

if [ "$OPEN_DIVS" -ne "$CLOSE_DIVS" ]; then
    echo -e "${RED}3. Div 标签数量不匹配${NC}"
    ISSUES=$((ISSUES + 1))
fi

if [ ! -d "$FRONTEND_PATH/.next" ]; then
    echo -e "${RED}4. 前端未构建，需要运行 npm run build${NC}"
    ISSUES=$((ISSUES + 1))
fi

if [ $ISSUES -eq 0 ]; then
    echo -e "${GREEN}没有发现明显问题，代码看起来正确。${NC}"
    echo "如果问题仍然存在，可能是:"
    echo "  - 浏览器缓存 (清除缓存后刷新)"
    echo "  - CDN 缓存"
    echo "  - 服务未重启"
fi

echo ""
echo "========================================"
echo "   修复建议"
echo "========================================"
if [ $ISSUES -gt 0 ]; then
    echo ""
    echo "运行以下命令修复:"
    echo ""
    echo "  cd $PROJECT_PATH"
    echo "  git fetch origin"
    echo "  git checkout claude/review-and-improve-codebase-56nE1"
    echo "  git pull origin claude/review-and-improve-codebase-56nE1"
    echo "  cd web/frontend"
    echo "  npm install"
    echo "  npm run build"
    echo "  sudo systemctl restart algvex-frontend"
    echo ""
fi
